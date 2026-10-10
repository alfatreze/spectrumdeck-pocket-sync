#!/usr/bin/env python3
"""Prepare a reviewed immutable library bundle for the Pocket Sync WASI plugin."""
import argparse
import json
from pathlib import Path
import shutil
import tempfile
import catalog
import pack_import
import pack_ingest

TARGET='Assets/spectrumdeck/common/library'

def prepare(source, library, plan, output, metadata=None, default_model='48k', allow_fixtures=False):
    source=Path(source);library=Path(library);output=Path(output)
    catalog.require(not output.exists(),'bundle output already exists')
    catalog.require(not output.resolve().is_relative_to(source.resolve()),'bundle must be outside input')
    catalog.require(not output.resolve().is_relative_to(library.resolve()),'bundle must be outside library')
    prior=pack_import.base_record(library)
    with tempfile.TemporaryDirectory(prefix='spectrumdeck-bundle-') as temporary:
        mirror=Path(temporary)/'library';mirror.mkdir()
        if prior:
            base=library/prior['directory'];destination=mirror/prior['directory']
            destination.mkdir(parents=True)
            for name in prior['files']:
                src=catalog.asset(base,name);dst=destination/name;dst.parent.mkdir(parents=True,exist_ok=True)
                shutil.copyfile(src,dst)
            (mirror/'publication-a.json').write_text(json.dumps(prior))
            catalog.require(pack_ingest.verified_publications(mirror)==[prior],'source library changed during bundle preparation')
        record,report=pack_import.import_pack(source,mirror,plan,metadata,default_model,allow_fixtures)
        catalog.require(pack_import.base_record(library)==prior,'source library changed during bundle preparation')
        output.mkdir(parents=True)
        try:
            shutil.copytree(mirror/record['directory'],output/record['directory'])
            manifest={'version':1,'target':TARGET,'expectedPrior':prior,'publication':record,
                      'summary':{'added':len(report['included']),'retained':report['retainedReleases'],
                                 'unidentified':len(report['unknown'])}}
            (output/'bundle.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
            return manifest
        except BaseException:
            shutil.rmtree(output);raise

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source',type=Path);parser.add_argument('library',type=Path)
    parser.add_argument('output',type=Path);parser.add_argument('--plan',type=Path,required=True)
    parser.add_argument('--metadata',type=Path);parser.add_argument('--default-model',choices=catalog.MODELS,default='48k')
    parser.add_argument('--allow-fixtures',action='store_true');args=parser.parse_args()
    try:
        manifest=prepare(args.source,args.library,json.loads(args.plan.read_text()),args.output,
                         json.loads(args.metadata.read_text()) if args.metadata else None,args.default_model,args.allow_fixtures)
        print(json.dumps(manifest,indent=2))
    except (ValueError,OSError) as error:parser.exit(2,f'Bundle failed: {error}\n')
if __name__=='__main__':main()
