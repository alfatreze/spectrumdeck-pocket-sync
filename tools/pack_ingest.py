#!/usr/bin/env python3
"""Offline folder/pack importer and verified generation publisher.

No network, ROM bundling, compatibility inference or Pocket Sync integration.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import uuid
import catalog

NAMESPACE=uuid.UUID('ce3176ca-78d2-464e-a07e-9e08b728a44e')

def digest(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

def scan(root,metadata=None,default_model='48k',allow_fixtures=False):
    root=Path(root)
    catalog.require(root.is_dir() and not root.is_symlink(),'import root must be a real directory')
    catalog.require(default_model in catalog.MODELS,'default model')
    metadata={} if metadata is None else metadata
    catalog.require(isinstance(metadata,dict),'metadata mapping')
    for sha,item in metadata.items():
        catalog.require(isinstance(sha,str) and len(sha)==64 and all(c in '0123456789abcdef' for c in sha),'metadata hash')
        catalog.keys(item,('gameId','title','details','model','source'))
        uuid.UUID(item['gameId']);catalog.text(item['title'],'title',255);catalog.text(item['details'],'details')
        catalog.require(item['model'] in catalog.MODELS,'metadata model');catalog.text(item['source'],'source')
    seen={};groups={};report={'included':[],'duplicates':[],'excluded':[],'unknown':[],'defaultModel':default_model,'compatibility':'unqualified; no launch recipes'}
    formats=set(catalog.FORMATS)-{'fixture'}
    if allow_fixtures:formats.add('fixture')
    for folder,dirs,files in os.walk(root,followlinks=False):
        folder=Path(folder)
        for name in list(dirs):
            if (folder/name).is_symlink():
                dirs.remove(name);report['excluded'].append({'path':(folder/name).relative_to(root).as_posix(),'reason':'symlink directory'})
        dirs.sort()
        for name in sorted(files):
            path=folder/name;relative=path.relative_to(root).as_posix();fmt=path.suffix.lower().lstrip('.')
            if path.is_symlink():report['excluded'].append({'path':relative,'reason':'symlink'});continue
            if fmt not in formats:continue
            try:
                catalog.relative_path(relative);size=path.stat().st_size
                catalog.require(0<size<=0xffffffff,'empty or >4 GB media');sha=digest(path)
                if sha in seen:
                    report['duplicates'].append({'path':relative,'canonical':seen[sha]['source'],'sha256':sha,'formatConflict':fmt!=seen[sha]['format']});continue
                item=metadata.get(sha)
                if item:
                    identity=str(uuid.UUID(item['gameId']));title=item['title'];details=item['details'];model=item['model'];source=item['source']
                else:
                    identity=str(uuid.uuid5(NAMESPACE,sha));title=path.stem;details='Unidentified import. Model is an import assumption; use native/manual launch until qualified.';model=default_model;source=None
                    catalog.require(0<len(title.encode())<=255,'title length')
                    report['unknown'].append({'path':relative,'sha256':sha,'assumedModel':model})
                existing=groups.get(identity)
                if existing:catalog.require(existing['title']==title and existing['details']==details,'conflicting game metadata')
                else:
                    catalog.require(len(groups)<catalog.MAX_GAMES,'game limit')
                    groups[identity]={'id':identity,'title':title,'details':details,'releases':[]}
                # Content-addressed paths survive source renames and avoid pack collisions.
                release={'path':f'media/{sha}.{fmt}','format':fmt,'model':model,'label':relative,'sha256':sha}
                groups[identity]['releases'].append(release)
                seen[sha]={'source':relative,'format':fmt,'bytes':size,'target':release['path']}
                report['included'].append({'path':relative,'sha256':sha,'gameId':identity,'source':source})
            except (ValueError,OSError) as error:report['excluded'].append({'path':relative,'reason':str(error)})
    games=sorted(groups.values(),key=lambda g:(catalog.sort_alias(g['title']),g['id']))
    return games,seen,report

def _write(path,data):
    with path.open('xb') as stream:stream.write(data);stream.flush();os.fsync(stream.fileno())

def _sync_directory(path):
    descriptor=os.open(path,os.O_RDONLY)
    try:os.fsync(descriptor)
    finally:os.close(descriptor)

def verified_publications(output):
    output=Path(output);valid=[]
    for slot in ('publication-a.json','publication-b.json'):
        try:
            pointer=output/slot;catalog.require(not pointer.is_symlink(),'symlink publication')
            record=json.loads(pointer.read_text());catalog.keys(record,('version','sequence','directory','files'))
            catalog.require(record['version']==1 and type(record['sequence']) is int and record['sequence']>=1,'publication version/sequence')
            catalog.require(isinstance(record['files'],dict) and {'index.bin','catalog.json','import-report.json'}.issubset(record['files']),'publication inventory')
            directory=record['directory'];catalog.relative_path(directory)
            catalog.require(len(Path(directory).parts)==2 and Path(directory).parts[0]=='generations','generation directory')
            base=output/directory;catalog.require(not base.is_symlink() and not (output/'generations').is_symlink(),'symlink generation')
            for name,sha in record['files'].items():
                path=catalog.asset(base,name)
                catalog.require(not path.is_symlink() and digest(path)==sha,'publication digest mismatch')
            index=catalog.decode_catalog((base/'index.bin').read_bytes())
            catalog.require(index['generation']==record['sequence'],'generation mismatch')
            # Manifest cannot omit any media referenced by the index.
            for release in index['releases']:
                catalog.require(record['files'].get(release['path'])==release['sha256'],'missing media verification')
                catalog.require((base/release['path']).stat().st_size==release['bytes'],'media size mismatch')
            valid.append(record)
        except (OSError,ValueError,TypeError,KeyError):continue
    return sorted(valid,key=lambda r:r['sequence'],reverse=True)

def publish(root,output,metadata=None,default_model='48k',allow_fixtures=False,fault=None,prepared=None,expected_prior=None):
    """Single-writer local publication. `fault` is a test-only interruption hook."""
    root=Path(root);output=Path(output)
    catalog.require(not output.is_symlink(),'symlink output')
    # Prevent recursively re-importing generated copies.
    catalog.require(not output.resolve().is_relative_to(root.resolve()),'output must be outside import root')
    output.mkdir(parents=True,exist_ok=True)
    generations=output/'generations';catalog.require(not generations.is_symlink(),'symlink generations');generations.mkdir(exist_ok=True)
    # Exclusive lock protects read-sequence/write-slot against concurrent publishers.
    lock=output/'.publish.lock';descriptor=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    try:
        os.write(descriptor,str(os.getpid()).encode());os.fsync(descriptor)
        prior=verified_publications(output);sequence=(prior[0]['sequence']+1) if prior else 1
        if expected_prior is not None:
            catalog.require((prior[0] if prior else {})==expected_prior,'library changed since preview; preview again')
        catalog.require(sequence<=0xffffffff,'generation exhausted')
        games,media,report=scan(root,metadata,default_model,allow_fixtures) if prepared is None else prepared
        if fault:fault('scan-complete')
        directory=f'generations/{sequence:010}-{uuid.uuid4().hex}'
        base=output/directory;base.mkdir();(base/'media').mkdir()
        for sha,item in media.items():
            source=catalog.asset(root,item['source']);catalog.require(not source.is_symlink(),'source symlink changed')
            destination=base/item['target']
            with source.open('rb') as src,destination.open('xb') as dst:
                shutil.copyfileobj(src,dst,256*1024);dst.flush();os.fsync(dst.fileno())
            catalog.require(digest(destination)==sha and destination.stat().st_size==item['bytes'],'media changed during import')
        manifest={'schemaVersion':1,'generation':sequence,'games':games}
        binary=catalog.compile_catalog(manifest,base,allow_fixtures)
        _write(base/'index.bin',binary)
        _write(base/'catalog.json',(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n').encode())
        _write(base/'import-report.json',(json.dumps(report,ensure_ascii=False,indent=2)+'\n').encode())
        files={p.relative_to(base).as_posix():digest(p) for p in sorted(base.rglob('*')) if p.is_file()}
        _sync_directory(base/'media');_sync_directory(base);_sync_directory(generations)
        record={'version':1,'sequence':sequence,'directory':directory,'files':files}
        if fault:fault('generation-ready')
        # Replace the older slot, preserving the newest validated generation.
        newest_slot=None
        if prior:
            for slot in ('publication-a.json','publication-b.json'):
                try:
                    if json.loads((output/slot).read_text()).get('directory')==prior[0]['directory']:newest_slot=slot
                except (OSError,ValueError,AttributeError):pass
        slot='publication-b.json' if newest_slot=='publication-a.json' else 'publication-a.json'
        temporary=output/f'.{uuid.uuid4().hex}.tmp';_write(temporary,(json.dumps(record,indent=2)+'\n').encode())
        if fault:fault('before-commit')
        os.replace(temporary,output/slot);_sync_directory(output)
        if fault:fault('after-commit')
        catalog.require(any(r['directory']==directory for r in verified_publications(output)),'publication verification failed')
        return record,report
    finally:
        os.close(descriptor);lock.unlink()

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('root',type=Path);parser.add_argument('output',type=Path)
    parser.add_argument('--metadata',type=Path);parser.add_argument('--default-model',choices=catalog.MODELS,default='48k');parser.add_argument('--allow-fixtures',action='store_true')
    args=parser.parse_args();metadata=json.loads(args.metadata.read_text()) if args.metadata else None
    record,report=publish(args.root,args.output,metadata,args.default_model,args.allow_fixtures)
    print(json.dumps({'generation':record['sequence'],'directory':record['directory'],'included':len(report['included']),'unknown':len(report['unknown']),'duplicates':len(report['duplicates']),'excluded':report['excluded']},indent=2))

if __name__=='__main__':main()
