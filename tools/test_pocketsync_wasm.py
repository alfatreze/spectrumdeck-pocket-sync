#!/usr/bin/env python3
"""Execute the real WASI plugin with Pocket Sync's mounts/messages; disposable card only."""
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'tools'))
import extism
from pack_import import preview
from pack_ingest import verified_publications
from pocketsync_bundle import prepare,TARGET
LOG=[]
@extism.host_fn()
def print_msg(message: str) -> int:
    LOG.append(message)
    return 0

def main():
    wasm=ROOT/'target/wasm32-wasip1/release/spectrumdeck_pocket_plugin.wasm'
    with tempfile.TemporaryDirectory(prefix='spectrumdeck-pocketsync-test-') as temporary:
        base=Path(temporary);host=base/'host';pocket=base/'pocket';pack=base/'pack'
        host.mkdir();pocket.mkdir();pack.mkdir();library=pocket/TARGET
        (pack/'Original.tap').write_bytes(b'original non-playable test content')
        first=prepare(pack,library,preview(pack,library),host/'bundles'/'first')
        manifest={'wasm':[{'path':str(wasm)}],'allowed_paths':{str(host):'host',str(pocket):'pocket'},'allowed_hosts':[]}
        with extism.Plugin(manifest,wasi=True) as plugin:
            def call(name,value=None):return json.loads(plugin.call(name,b'' if value is None else json.dumps(value).encode()))
            def answer(name,value):return call('handle_response',{'Answer':{'name':name,'value':value}})
            assert 'Choice' in call('start')
            assert 'Text' in answer('menu','Publish prepared bundle')
            confirmation=answer('bundle','first');assert confirmation['Choice']['name']=='confirm'
            answer('confirm','Cancel');assert not library.exists()
            answer('bundle','../escape');assert 'bundle name' in LOG[-1]
            answer('bundle','first');answer('confirm','Publish')
            assert verified_publications(library)[0]==first['publication'], ''.join(LOG)
            profile=library/'profiles'/'user.json';profile.parent.mkdir();profile.write_bytes(b'user-owned')
            # Same bundle is safely idempotent.
            answer('bundle','first');answer('confirm','Publish')
            assert verified_publications(library)[0]['sequence']==1
            (pack/'Second.z80').write_bytes(b'another original non-playable test')
            second=prepare(pack,library,preview(pack,library),host/'bundles'/'second')
            # Rejection after a corrupted source leaves publication unchanged.
            media=next((host/'bundles'/'second'/second['publication']['directory']/'media').iterdir())
            original=media.read_bytes();media.write_bytes(b'corrupt');answer('bundle','second')
            assert 'digest mismatch' in LOG[-1];media.write_bytes(original)
            answer('bundle','second');answer('confirm','Publish')
            assert verified_publications(library)[0]==second['publication'], ''.join(LOG)
            assert profile.read_bytes()==b'user-owned'
            # A stale bundle cannot overwrite the newly published generation.
            answer('bundle','first');answer('confirm','Publish')
            assert any('library changed' in line for line in LOG)
            assert verified_publications(library)[0]['sequence']==2
            answer('menu','Inspect current library');assert 'Verified generation 2' in LOG[-1]
            assert call('handle_response','Kill')=='Exit'
            # Structural corruption with recomputed inventory hashes must fail.
            bad=host/'bundles'/'invalid';shutil.copytree(host/'bundles'/'second',bad)
            document=json.loads((bad/'bundle.json').read_text());index=bad/document['publication']['directory']/'index.bin'
            index.write_bytes(b'not an index');document['publication']['files']['index.bin']=hashlib.sha256(index.read_bytes()).hexdigest()
            (bad/'bundle.json').write_text(json.dumps(document));call('start');answer('bundle','invalid')
            assert 'index length' in LOG[-1]
        print(json.dumps({'runtime':extism.extism_version(),'wasmSha256':hashlib.sha256(wasm.read_bytes()).hexdigest(),
                          'checks':['Pocket Sync mount and JSON ABI','cancel before write','unsafe bundle name','actual WASI first publication','idempotent retry','corrupt source rejection','additive generation','preset preservation','stale bundle rejection','verified inspection','Kill message','structural index rejection'],
                          'log':LOG},indent=2))
if __name__=='__main__':main()
