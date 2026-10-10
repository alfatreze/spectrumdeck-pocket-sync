#!/usr/bin/env python3
"""Byte comparison of the native Rust catalog encoder and Python reference."""
import hashlib,json,subprocess,sys,tempfile,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'tools'))
import catalog
with tempfile.TemporaryDirectory() as temporary:
    root=Path(temporary)
    titles=['Orbit Station','Straße','Ångström','İstanbul','CAFÉ','Σίσυφος','Жук','日本語','ﬁ ligature','ẞ test']
    for generation in (1,2,0xffffffff):
        games=[];sizes={}
        for i,title in enumerate(titles):
            releases=[]
            for j in range(1+(i%3)):
                path=f'media/{i}-{j}.tap';data=f'original fixture {i} {j}'.encode();(root/'media').mkdir(exist_ok=True);(root/path).write_bytes(data);sizes[path]=len(data)
                releases.append({'path':path,'format':'tap','model':['48k','128k','pentagon'][i%3],'label':f'{title} / edition {j}','sha256':hashlib.sha256(data).hexdigest()})
            games.append({'id':str(uuid.UUID(int=i+1)),'title':title,'details':f'Original test description {title}','releases':releases,'defaultRelease':len(releases)-1,'collectionMask':i})
        document={'schemaVersion':1,'generation':generation,'games':games}
        (root/'catalog.json').write_text(json.dumps(document));(root/'sizes.json').write_text(json.dumps(sizes))
        subprocess.run([str(ROOT/'target/debug/examples/compile'),str(root/'catalog.json'),str(root/'sizes.json'),str(root/'rust.bin')],check=True)
        expected=catalog.compile_catalog(document,root);actual=(root/'rust.bin').read_bytes()
        assert actual==expected, f'Rust/Python catalog mismatch at generation {generation}'
    print('Byte-identical catalogs: 3 generations, 10 Unicode titles, 19 releases each.')
