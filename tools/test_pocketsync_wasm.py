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
        # Native first-publication path on a separate empty card.
        native_card=base/'empty-card';native_host=base/'native-host'
        native_card.mkdir();native_host.mkdir();(native_card/'games').mkdir()
        (native_card/'games'/'First.tap').write_bytes(b'first native non-playable fixture')
        native_manifest={**manifest,'allowed_paths':{str(native_host):'host',str(native_card):'pocket'}}
        with extism.Plugin(native_manifest,wasi=True) as native_plugin:
            def native_answer(name,value):return json.loads(native_plugin.call('handle_response',json.dumps({'Answer':{'name':name,'value':value}}).encode()))
            native_plugin.call('start',b'')
            assert native_answer('menu','Scan card folder')['Text']['name']=='scan-folder'
            native_answer('scan-folder','games')
            native_answer('scan-model','48k');native_answer('scan-confirm','Create/update library')
            assert verified_publications(native_card/TARGET)[0]['sequence']==1, ''.join(LOG)
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
            # Native loose-file scan, with a real card-folder ABI and no Python preparation.
            card_media=pocket/'Assets'/'zxspectrum'/'common';card_media.mkdir(parents=True)
            native=card_media/'Native.tap';native.write_bytes(b'native original test bytes')
            call('start')
            discovered=answer('menu','Scan card folder')['Choice']
            assert discovered['name']=='detected-folder'
            assert discovered['choices']==['Assets/zxspectrum','Enter folder manually','Cancel']
            assert verified_publications(library)[0]['sequence']==2
            assert answer('detected-folder','Cancel')['Choice']['name']=='menu'
            answer('menu','Scan card folder')
            assert answer('detected-folder','not-a-detected-folder')['Choice']['name']=='menu'
            assert answer('detected-folder','Assets/zxspectrum')['Choice']['name']=='menu'
            answer('menu','Scan card folder')
            assert answer('detected-folder','Enter folder manually')['Text']['name']=='scan-folder'
            answer('scan-folder','Assets/zxspectrum/common');answer('scan-model','Cancel')
            answer('menu','Scan card folder')
            assert answer('detected-folder','Assets/zxspectrum')['Choice']['name']=='scan-model'
            result=answer('scan-model','128k');assert result['Choice']['name']=='scan-confirm'
            answer('scan-confirm','Cancel');assert verified_publications(library)[0]['sequence']==2
            answer('scan-folder','Assets/zxspectrum/common');answer('scan-model','128k')
            native.write_bytes(b'changed after scan');answer('scan-confirm','Create/update library')
            assert 'source or library changed' in LOG[-1]
            assert verified_publications(library)[0]['sequence']==2
            native.write_bytes(b'native original test bytes')
            answer('scan-folder','Assets/zxspectrum/common');answer('scan-model','128k');answer('scan-confirm','Create/update library')
            third=verified_publications(library)[0];assert third['sequence']==3, ''.join(LOG)
            assert profile.read_bytes()==b'user-owned'
            import uuid
            decoded=json.loads((library/third['directory']/'catalog.json').read_text())
            sha=hashlib.sha256(native.read_bytes()).hexdigest()
            expected_id=str(uuid.uuid5(uuid.UUID('ce3176ca-78d2-464e-a07e-9e08b728a44e'),sha))
            game=next(g for g in decoded['games'] if g['id']==expected_id)
            assert game['releases'][0]['model']=='128k'
            answer('scan-folder','Assets/zxspectrum/common');result=answer('scan-model','128k')
            assert result['Choice']['name']=='menu'
            assert verified_publications(library)[0]['sequence']==3
            # Structural corruption with recomputed inventory hashes must fail.
            bad=host/'bundles'/'invalid';shutil.copytree(host/'bundles'/'second',bad)
            document=json.loads((bad/'bundle.json').read_text());index=bad/document['publication']['directory']/'index.bin'
            index.write_bytes(b'not an index');document['publication']['files']['index.bin']=hashlib.sha256(index.read_bytes()).hexdigest()
            (bad/'bundle.json').write_text(json.dumps(document));call('start');answer('bundle','invalid')
            assert 'index length' in LOG[-1]
        print(json.dumps({'runtime':extism.extism_version(),'wasmSha256':hashlib.sha256(wasm.read_bytes()).hexdigest(),
                          'checks':['Pocket Sync mount and JSON ABI','cancel before write','unsafe bundle name','actual WASI first publication','idempotent retry','corrupt source rejection','additive generation','preset preservation','stale bundle rejection','verified inspection','Kill message','structural index rejection','native scan confirmation/cancel','native stale review rejection','native additive publication','native UUID/model parity','native no-change scan','native first publication on empty card','discovery no-results manual fallback','detected folder choice is read-only','discovery cancel','expired or forged selection rejected','explicit manual fallback','detected folder enters model review'],
                          'log':LOG},indent=2))
if __name__=='__main__':main()
