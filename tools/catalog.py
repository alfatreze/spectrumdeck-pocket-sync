"""SpectrumDeck v1 catalog compiler and defensive host reference decoder.

No third-party dependencies. Firmware must port the bounds checks before use.
Paths are relative to one caller-selected Assets root; symlinks are not trusted.
"""
import argparse
import hashlib
import json
import struct
import unicodedata
import uuid
import zlib
from pathlib import Path, PurePosixPath

HEADER = struct.Struct('<8sHH9IHH3I')
GAME = struct.Struct('<16s4IHHIIHHII8s')
RELEASE = struct.Struct('<32sIIHH7I8s')
ART_HEADER = struct.Struct('<8sHH4H5I')
TILE = struct.Struct('<4s4HI')
FORMATS = {'fixture': 0, 'tap': 1, 'tzx': 2, 'z80': 3, 'sna': 4,
           'dsk': 5, 'trd': 6, 'vhd': 7, 'szx': 8}
MODELS = {'48k': 1, '128k': 2, 'pentagon': 3}
MAX_BYTES = 64 * 1024 * 1024
MAX_GAMES = 100_000
MAX_TEXT = 4096
CRC = lambda data: zlib.crc32(data) & 0xffffffff


def require(condition, message):
    if not condition:
        raise ValueError(message)


def integer(value, name, maximum=0xffffffff):
    require(type(value) is int and 0 <= value <= maximum, f'{name}: invalid integer')
    return value


def text(value, name, maximum=MAX_TEXT):
    require(isinstance(value, str) and '\0' not in value, f'{name}: invalid text')
    raw = value.encode('utf-8')
    require(len(raw) <= maximum, f'{name}: text too long')
    return raw


def relative_path(value):
    text(value, 'path', 255)
    require(value and '\\' not in value and ':' not in value, 'unsafe path')
    parts = value.split('/')
    require(all(p not in ('', '.', '..') for p in parts), 'unsafe path')
    require(not PurePosixPath(value).is_absolute(), 'absolute path')
    require(not any(ord(c) < 32 or ord(c) == 127 for c in value), 'control character in path')
    return value


def asset(root, name):
    name = relative_path(name)
    target = (root / name).resolve()
    require(target.is_relative_to(root.resolve()), 'asset escapes Assets root')
    require(target.is_file(), f'missing asset: {name}')
    return target


def keys(value, required, optional=()):
    require(isinstance(value, dict), 'expected object')
    require(set(required) <= value.keys(), f'missing keys: {set(required) - value.keys()}')
    require(value.keys() <= set(required) | set(optional), 'unknown authoring field')


def sort_alias(title):
    return ''.join(c for c in unicodedata.normalize('NFKD', title)
                   if not unicodedata.combining(c)).casefold()


def compile_catalog(manifest, root, allow_fixtures=False, artwork=None):
    keys(manifest, ('schemaVersion', 'generation', 'games'))
    require(type(manifest['schemaVersion']) is int and manifest['schemaVersion'] == 1,
            'unsupported authoring version')
    generation = integer(manifest['generation'], 'generation')
    games = manifest['games']
    require(isinstance(games, list) and len(games) <= MAX_GAMES, 'invalid game count')
    strings = bytearray()
    interned = {}

    def intern(value):
        raw = text(value, 'string')
        if value not in interned:
            interned[value] = len(strings)
            strings.extend(raw + b'\0')
        return interned[value]

    game_records, release_records, seen_games, seen_hashes = [], [], set(), set()
    for game in games:
        keys(game, ('id', 'title', 'details', 'releases'),
             ('defaultRelease', 'collectionMask', 'coverTile'))
        identity = uuid.UUID(game['id']).bytes
        require(identity not in seen_games, 'duplicate game ID')
        seen_games.add(identity)
        title = game['title']
        require(text(title, 'title', 255), 'empty title')
        detail = text(game['details'], 'details')
        releases = game['releases']
        require(isinstance(releases, list) and 0 < len(releases) <= 65535, 'invalid releases')
        first = len(release_records)
        default = integer(game.get('defaultRelease', 0), 'default release', len(releases)-1)
        for release in releases:
            keys(release, ('path', 'format', 'model', 'label', 'sha256'), ())
            require(release['format'] in FORMATS and release['model'] in MODELS, 'unknown format/model')
            require(allow_fixtures or release['format'] != 'fixture', 'fixture media requires --allow-fixtures')
            path = asset(root, release['path'])
            length = path.stat().st_size
            require(0 < length <= 0xffffffff, 'empty or >4 GB media')
            with path.open('rb') as stream:
                digest = hashlib.file_digest(stream, 'sha256').digest()
            require(digest.hex() == release['sha256'], 'media digest mismatch')
            require(digest not in seen_hashes, 'duplicate release hash')
            seen_hashes.add(digest)
            # No automatic recipe, dependencies or compatibility claim in this first compiler.
            release_records.append(RELEASE.pack(digest, intern(relative_path(release['path'])),
                length, FORMATS[release['format']], MODELS[release['model']],
                0, 0, 0, 0, 0, 0, intern(release['label']), bytes(8)))
        cover = game.get('coverTile')
        art_offset = art_length = 0
        if cover is not None:
            integer(cover, 'cover tile', (MAX_BYTES-ART_HEADER.size-768)//(TILE.size+8320)-1)
            art_offset, art_length = ART_HEADER.size + 768 + cover * (TILE.size + 8320), TILE.size + 8320
        game_records.append(GAME.pack(identity, intern(title), intern(sort_alias(title)),
            intern(game['details']), first, len(releases), 0, art_offset, art_length,
            default, 0, integer(game.get('collectionMask', 0), 'collection mask'), len(detail), bytes(8)))
    game_offset = HEADER.size
    release_offset = game_offset + len(game_records) * GAME.size
    string_offset = release_offset + len(release_records) * RELEASE.size
    payload = b''.join(game_records + release_records) + strings
    require(len(payload) + HEADER.size <= MAX_BYTES, 'catalog exceeds v1 size bound')
    fields = [b'SDEKIDX1', 1, 0, HEADER.size, HEADER.size+len(payload), generation,
              len(games), len(release_records), game_offset, release_offset, string_offset,
              len(strings), GAME.size, RELEASE.size, CRC(payload), 0, 0]
    fields[-2] = CRC(HEADER.pack(*fields))
    data = HEADER.pack(*fields) + payload
    decoded = decode_catalog(data)
    require(artwork is not None or not any(g['artLength'] for g in decoded['games']),
            'cover references require an artwork container')
    if artwork is not None:
        decode_artwork(artwork, decoded)
    return data


def decode_catalog(data):
    require(HEADER.size <= len(data) <= MAX_BYTES, 'invalid catalog length')
    (magic, major, minor, hb, total, generation, ng, nr, go, ro, so, ns,
     gs, rs, payload_crc, header_crc, flags) = HEADER.unpack_from(data)
    require(magic == b'SDEKIDX1' and major == 1, 'unsupported catalog')
    require(hb == 64 and total == len(data) and flags == 0, 'invalid header')
    header = bytearray(data[:hb])
    struct.pack_into('<I', header, 56, 0)
    require(CRC(header) == header_crc and CRC(data[hb:]) == payload_crc, 'catalog CRC mismatch')
    require(ng <= MAX_GAMES and nr <= MAX_GAMES * 16, 'record count exceeds bounds')
    require(gs >= GAME.size and rs >= RELEASE.size, 'short record stride')
    require(go == hb and ro == go + ng*gs and so == ro + nr*rs and total == so+ns,
            'invalid or overlapping sections')

    def string(offset):
        require(offset < ns, 'string offset out of range')
        require(offset == 0 or data[so+offset-1] == 0, 'string offset is not a string boundary')
        end = data.find(b'\0', so+offset, min(total, so+offset+MAX_TEXT+1))
        require(end >= 0, 'unterminated or overlong string')
        return data[so+offset:end].decode('utf-8', errors='strict')

    games, releases, seen_ids, seen_hashes = [], [], set(), set()
    for i in range(nr):
        r = RELEASE.unpack_from(data, ro+i*rs)
        digest, path, size, fmt, model, recipe, recipe_len, preset, dep, compat, volume, label, reserved = r
        require(reserved == bytes(8) and not any((recipe, recipe_len, preset, dep, compat, volume)),
                'unsupported release features')
        require(fmt in FORMATS.values() and model in MODELS.values() and size > 0, 'invalid media fields')
        require(digest not in seen_hashes, 'duplicate release identity')
        seen_hashes.add(digest)
        releases.append({'sha256': digest.hex(), 'path': relative_path(string(path)),
                         'bytes': size, 'formatId': fmt, 'modelId': model, 'label': string(label)})
    next_release = 0
    for i in range(ng):
        g = GAME.unpack_from(data, go+i*gs)
        identity, title, sort, detail, first, count, gf, ao, al, default, reserved16, collections, dl, reserved = g
        require(identity not in seen_ids, 'duplicate game identity')
        seen_ids.add(identity)
        require(gf == reserved16 == 0 and reserved == bytes(8), 'unknown game flags/reserved fields')
        require(first == next_release and count > 0 and first+count <= nr and default < count,
                'invalid release ownership/default')
        next_release += count
        details = string(detail)
        require(len(details.encode('utf-8')) == dl, 'detail length mismatch')
        require((ao == al == 0) or (al == TILE.size+8320 and ao >= ART_HEADER.size+768
                 and (ao-ART_HEADER.size-768) % al == 0), 'invalid artwork reference')
        require(text(string(title), 'title', 255), 'empty title')
        games.append({'id': str(uuid.UUID(bytes=identity)), 'title': string(title),
                      'sort': string(sort), 'details': details, 'firstRelease': first,
                      'releaseCount': count, 'defaultRelease': default,
                      'collectionMask': collections, 'artOffset': ao, 'artLength': al})
    require(next_release == nr, 'orphan releases')
    return {'version': [major, minor], 'generation': generation, 'games': games, 'releases': releases}


def encode_artwork(palette, tiles):
    require(len(palette) == 768 and all(len(t) == 8320 for t in tiles), 'invalid artwork dimensions')
    payload = palette + b''.join(TILE.pack(b'TILE', 80, 104, 80, 0, CRC(t)) + t for t in tiles)
    fields = [b'SDEKART1', 1, 0, 80, 104, 80, 256, 1, len(tiles),
              ART_HEADER.size+len(payload), CRC(payload), 0]
    fields[-1] = CRC(ART_HEADER.pack(*fields))
    return ART_HEADER.pack(*fields) + payload


def decode_artwork(data, catalog):
    require(ART_HEADER.size <= len(data) <= MAX_BYTES, 'invalid artwork length')
    magic, major, minor, w, h, stride, colors, pv, count, total, pc, hc = ART_HEADER.unpack_from(data)
    require((magic, major, minor, w, h, stride, colors, pv) ==
            (b'SDEKART1', 1, 0, 80, 104, 80, 256, 1), 'unsupported artwork')
    header = bytearray(data[:ART_HEADER.size])
    struct.pack_into('<I', header, 36, 0)
    require(total == len(data) == ART_HEADER.size+768+count*(TILE.size+8320), 'artwork bounds mismatch')
    require(CRC(header) == hc and CRC(data[ART_HEADER.size:]) == pc, 'artwork CRC mismatch')
    for i in range(count):
        offset = ART_HEADER.size+768+i*(TILE.size+8320)
        tag, tw, th, ts, reserved, crc = TILE.unpack_from(data, offset)
        require((tag, tw, th, ts, reserved) == (b'TILE', 80, 104, 80, 0), 'invalid tile header')
        require(CRC(data[offset+TILE.size:offset+TILE.size+8320]) == crc, 'tile CRC mismatch')
    for game in catalog['games']:
        if game['artLength']:
            require(game['artOffset']+game['artLength'] <= total, 'missing cover tile')
    return {'tiles': count, 'paletteVersion': pv}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    build = sub.add_parser('compile')
    build.add_argument('manifest', type=Path)
    build.add_argument('--assets-root', required=True, type=Path)
    build.add_argument('--output', required=True, type=Path)
    build.add_argument('--artwork', type=Path)
    build.add_argument('--allow-fixtures', action='store_true')
    inspect = sub.add_parser('inspect')
    inspect.add_argument('index', type=Path)
    inspect.add_argument('--artwork', type=Path)
    args = parser.parse_args()
    if args.command == 'compile':
        data = compile_catalog(json.loads(args.manifest.read_text()), args.assets_root, args.allow_fixtures,
                               args.artwork.read_bytes() if args.artwork else None)
        decode_catalog(data)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(data)
        print(json.dumps({'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}))
    else:
        catalog = decode_catalog(args.index.read_bytes())
        if args.artwork:
            catalog['artwork'] = decode_artwork(args.artwork.read_bytes(), catalog)
        print(json.dumps(catalog, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
