#!/usr/bin/env python3
"""Reviewed, additive local folder/ZIP/TAR import. No network or media qualification."""
import argparse
from contextlib import contextmanager
import copy
import hashlib
import json
from pathlib import Path
import shutil
import stat
import tarfile
import tempfile
import zipfile
import catalog
import pack_ingest as ingest

MAX_MEMBERS = 100_000
MAX_FILE = 256 * 1024 * 1024
MAX_TOTAL = 2 * 1024 * 1024 * 1024


def encoded(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()


@contextmanager
def input_root(source):
    """Reject unsafe archives as a unit; stream into a private disposable directory."""
    source = Path(source)
    catalog.require(not source.is_symlink(), 'symlink input')
    if source.is_dir():
        yield source, {'kind': 'folder'}
        return
    catalog.require(source.is_file(), 'missing input')
    catalog.require(source.stat().st_size <= MAX_TOTAL, 'archive input size limit')
    before = ingest.digest(source)
    with tempfile.TemporaryDirectory(prefix='spectrumdeck-pack-') as temporary:
        root = Path(temporary)
        paths = set(); components = {}; total = 0; count = 0

        def destination(name, size, directory=False):
            nonlocal total, count
            count += 1
            catalog.require(count <= MAX_MEMBERS, 'archive member limit')
            name = name.rstrip('/') if directory else name
            catalog.relative_path(name)
            # FAT-style aliases and file/directory collisions cannot be silently overwritten.
            folded = name.casefold()
            parts = Path(name).parts
            for end in range(1, len(parts) + 1):
                spelling = '/'.join(parts[:end]); key = spelling.casefold()
                catalog.require(components.get(key, spelling) == spelling, 'case-colliding archive path')
                components[key] = spelling
            catalog.require(folded not in paths, 'duplicate archive path')
            for parent in Path(name).parents:
                if str(parent) != '.':
                    catalog.require(('file:' + parent.as_posix().casefold()) not in paths, 'archive parent is a file')
            catalog.require(directory or not any(p.startswith(folded + '/') for p in paths), 'archive file replaces directory')
            paths.add(folded)
            if not directory: paths.add('file:' + folded)
            catalog.require(0 <= size <= MAX_FILE, 'archive file size limit')
            total += size
            catalog.require(total <= MAX_TOTAL, 'archive expanded size limit')
            target = root / name
            if directory: target.mkdir(parents=True, exist_ok=True)
            else: target.parent.mkdir(parents=True, exist_ok=True)
            return target

        def transfer(stream, target, size):
            remaining = size
            with target.open('xb') as output:
                while remaining:
                    chunk = stream.read(min(remaining, 256 * 1024))
                    catalog.require(bool(chunk), 'truncated archive member')
                    output.write(chunk); remaining -= len(chunk)
                catalog.require(not stream.read(1), 'archive member size mismatch')

        if zipfile.is_zipfile(source):
            with zipfile.ZipFile(source) as archive:
                catalog.require(len(archive.infolist()) <= MAX_MEMBERS, 'archive member limit')
                for member in archive.infolist():
                    mode = member.external_attr >> 16
                    catalog.require(not member.flag_bits & 1, 'encrypted ZIP unsupported')
                    catalog.require(stat.S_IFMT(mode) in (0, stat.S_IFREG, stat.S_IFDIR), 'archive special file/link')
                    target = destination(member.filename, member.file_size, member.is_dir())
                    if not member.is_dir():
                        with archive.open(member) as stream: transfer(stream, target, member.file_size)
            kind = 'zip'
        else:
            try:
                with tarfile.open(source, 'r|*') as archive:
                    for member in archive:
                        catalog.require(member.isdir() or member.isfile(), 'archive special file/link')
                        target = destination(member.name, member.size, member.isdir())
                        if member.isfile():
                            with archive.extractfile(member) as stream: transfer(stream, target, member.size)
                kind = 'tar'
            except tarfile.TarError as error:
                raise ValueError('unsupported or damaged archive') from error
        catalog.require(ingest.digest(source) == before, 'archive changed while reading')
        yield root, {'kind': kind, 'sha256': before}


def inventory(root, metadata, model, fixtures):
    games, media, report = ingest.scan(root, metadata, model, fixtures)
    candidates = {sha: [item['source']] for sha, item in media.items()}
    for alias in report['duplicates']:
        candidates[alias['sha256']].append(alias['path'])
    return games, media, report, candidates


def base_record(output):
    records = ingest.verified_publications(output) if output else []
    if output and Path(output).exists() and not records:
        catalog.require(not any((Path(output)/s).exists() for s in ('publication-a.json', 'publication-b.json')),
                        'no valid library generation; repair before import')
    return records[0] if records else {}


def make_preview(root, provenance, output, metadata, model, fixtures):
    games, media, report, candidates = inventory(root, metadata, model, fixtures)
    base = base_record(output)
    choices = {}
    for sha, paths in candidates.items():
        formats = {Path(p).suffix.lower() for p in paths}
        choices[sha] = None if len(formats) > 1 else paths[0]
    snapshot = {'provenance': provenance, 'games': games, 'media': media, 'report': report,
                'candidates': candidates, 'metadata': metadata or {}, 'model': model,
                'fixtures': fixtures, 'base': base}
    return {'version': 1, 'fingerprint': hashlib.sha256(encoded(snapshot)).hexdigest(),
            'source': provenance, 'baseGeneration': base.get('sequence', 0),
            'baseFingerprint': hashlib.sha256(encoded(base)).hexdigest(),
            'choices': choices, 'candidates': candidates, 'report': report,
            'unresolvedFormats': [sha for sha, path in choices.items() if path is None]}


def preview(source, output=None, metadata=None, default_model='48k', allow_fixtures=False):
    with input_root(source) as (root, provenance):
        return make_preview(root, provenance, output, metadata, default_model, allow_fixtures)


def import_pack(source, output, plan, metadata=None, default_model='48k', allow_fixtures=False, fault=None):
    catalog.keys(plan, ('version','fingerprint','source','baseGeneration','baseFingerprint','choices','candidates','report','unresolvedFormats'))
    catalog.require(type(plan['version']) is int and plan['version'] == 1 and isinstance(plan['choices'], dict), 'invalid import plan')
    source = Path(source); output = Path(output)
    catalog.require(not output.resolve().is_relative_to(source.resolve()), 'output must be outside input')
    with input_root(source) as (root, provenance):
        fresh = make_preview(root, provenance, output, metadata, default_model, allow_fixtures)
        catalog.require(plan['fingerprint'] == fresh['fingerprint'], 'input, metadata or library changed; preview again')
        catalog.require(set(plan['choices']) == set(fresh['choices']), 'choice hashes differ from preview')
        prior = base_record(output)
        catalog.require(hashlib.sha256(encoded(prior)).hexdigest() == fresh['baseFingerprint'],
                        'library changed since preview; preview again')
        with tempfile.TemporaryDirectory(prefix='spectrumdeck-selected-') as temporary:
            staging = Path(temporary)
            report = copy.deepcopy(fresh['report']); report['source'] = provenance
            report['choices'] = copy.deepcopy(plan['choices'])
            report['skipped'] = []; report['alreadyPresent'] = []; report['metadataConflicts'] = []
            report['included'] = []; report['unknown'] = []
            games = []; media = {}; by_id = {}; existing = set()
            if prior:
                base = output / prior['directory']
                manifest = json.loads((base / 'catalog.json').read_text())
                games = copy.deepcopy(manifest['games']); by_id = {g['id']: g for g in games}
                for game in games:
                    for release in game['releases']:
                        sha = release['sha256']; existing.add(sha)
                        src = catalog.asset(base, release['path']); target = staging/release['path']
                        target.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(src, target)
                        media[sha] = {'source': release['path'], 'target': release['path'],
                                      'format': release['format'], 'bytes': src.stat().st_size}
            for sha, choice in plan['choices'].items():
                if choice is None:
                    report['skipped'].append({'sha256': sha, 'reason': 'review choice or unresolved format'}); continue
                catalog.require(isinstance(choice, str) and choice in fresh['candidates'][sha], 'choice is not a preview candidate')
                if sha in existing:
                    report['alreadyPresent'].append({'sha256': sha, 'path': choice}); continue
                src = catalog.asset(root, choice)
                # Scan one selection in isolation: explicit format decisions cannot be
                # overridden by lexical ordering of aliases, and work stays linear.
                selection = staging/'selection'; selection.mkdir()
                selected = selection/Path(choice).name
                shutil.copyfile(src, selected)
                catalog.require(ingest.digest(selected) == sha, 'media changed since preview')
                selected_games, selected_media, selected_report = ingest.scan(selection, {sha: metadata[sha]} if metadata and sha in metadata else {}, default_model, allow_fixtures)
                catalog.require(sha in selected_media, 'selected media was excluded')
                item = selected_media[sha]
                source_name = 'incoming/' + sha + '.' + item['format']
                target = staging/source_name; target.parent.mkdir(parents=True, exist_ok=True)
                selected.rename(target); selection.rmdir()
                item['source'] = source_name
                game = selected_games[0]; release = game['releases'][0]; release['label'] = choice
                for category in ('included', 'unknown'):
                    for entry in selected_report[category]: entry['path'] = choice
                if game['id'] in by_id:
                    previous = by_id[game['id']]
                    if (previous['title'],previous['details']) != (game['title'],game['details']):
                        report['metadataConflicts'].append({'gameId':game['id'],'policy':'retain existing title/details'})
                    previous['releases'].append(release)
                else:
                    game['releases'] = [release]; games.append(game); by_id[game['id']] = game
                media[sha] = item
                report['included'].extend(i for i in selected_report['included'] if i['sha256'] == sha)
                report['unknown'].extend(i for i in selected_report['unknown'] if i['sha256'] == sha)
            games.sort(key=lambda g:(catalog.sort_alias(g['title']),g['id']))
            report['retainedReleases'] = len(existing)
            catalog.require(report['included'], 'no new releases selected; library unchanged')
            return ingest.publish(staging, output, allow_fixtures=allow_fixtures, fault=fault,
                                  prepared=(games,media,report), expected_prior=prior)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('preview','import'))
    parser.add_argument('source', type=Path); parser.add_argument('output', type=Path)
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--metadata', type=Path)
    parser.add_argument('--default-model', choices=catalog.MODELS, default='48k')
    parser.add_argument('--allow-fixtures', action='store_true')
    args = parser.parse_args()
    metadata = json.loads(args.metadata.read_text()) if args.metadata else None
    try:
        if args.command == 'preview':
            result = preview(args.source,args.output,metadata,args.default_model,args.allow_fixtures)
            args.plan.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
            print(json.dumps({'plan':str(args.plan),'candidates':len(result['choices']),
                              'unresolvedFormats':result['unresolvedFormats'],'unknown':result['report']['unknown']},indent=2))
        else:
            record, report = import_pack(args.source,args.output,json.loads(args.plan.read_text()),metadata,args.default_model,args.allow_fixtures)
            print(json.dumps({'generation':record['sequence'],'directory':record['directory'],'report':report},indent=2))
    except (ValueError,OSError,zipfile.BadZipFile,RuntimeError) as error:
        parser.exit(2, f'Import failed: {error}\n')


if __name__ == '__main__': main()
