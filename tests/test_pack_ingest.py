import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'tools'))
from pack_ingest import scan,publish,verified_publications

class PackTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        base=Path(self.tmp.name);self.root=base/'pack';self.root.mkdir();self.out=base/'published'
        (self.root/'Unknown.tap').write_bytes(b'original test bytes, not playable');(self.root/'copy.tap').write_bytes((self.root/'Unknown.tap').read_bytes())
        (self.root/'empty.z80').write_bytes(b'');(self.root/'escape.tap').symlink_to('/etc/hosts')
    def test_determinism_unknown_duplicates_and_symlinks(self):
        a=scan(self.root);b=scan(self.root);self.assertEqual(a,b)
        games,media,report=a;self.assertEqual(len(games),1);self.assertEqual(len(media),1)
        self.assertEqual(len(report['duplicates']),1);self.assertEqual(len(report['unknown']),1);self.assertEqual(len(report['excluded']),2)
    def test_metadata_grouping_and_hash_identity(self):
        sha=hashlib.sha256((self.root/'Unknown.tap').read_bytes()).hexdigest()
        metadata={sha:{'gameId':'11111111-1111-4111-8111-111111111111','title':'Known title','details':'User-supplied identification','model':'128k','source':'local pack sidecar'}}
        games,_,report=scan(self.root,metadata);self.assertEqual(games[0]['title'],'Known title');self.assertEqual(games[0]['releases'][0]['model'],'128k');self.assertFalse(report['unknown'])
    def test_commit_interruption_and_corrupt_latest_fallback(self):
        first,_=publish(self.root,self.out);self.assertEqual(verified_publications(self.out)[0]['sequence'],1)
        for stage in ('generation-ready','before-commit'):
            def fault(value):
                if value==stage:raise RuntimeError('simulated interruption')
            with self.assertRaises(RuntimeError):publish(self.root,self.out,fault=fault)
            self.assertEqual(verified_publications(self.out)[0]['sequence'],1)
        second,_=publish(self.root,self.out);self.assertEqual(second['sequence'],2)
        (self.out/second['directory']/'index.bin').write_bytes(b'corrupt')
        self.assertEqual(verified_publications(self.out)[0]['directory'],first['directory'])
    def test_source_changes_fail_before_commit(self):
        first,_=publish(self.root,self.out)
        def fault(stage):
            if stage=='scan-complete':(self.root/'Unknown.tap').write_bytes(b'changed while importing')
        with self.assertRaises(ValueError):publish(self.root,self.out,fault=fault)
        self.assertEqual(verified_publications(self.out)[0],first)
        with self.assertRaises(ValueError):publish(self.root,self.root/'nested')
        lock=self.out/'.publish.lock';lock.write_text('occupied')
        with self.assertRaises(FileExistsError):publish(self.root,self.out)
        self.assertEqual(verified_publications(self.out)[0],first)
    def test_corrupt_media_invalidates_publication(self):
        record,_=publish(self.root,self.out)
        media=next((self.out/record['directory']/'media').iterdir());media.write_bytes(b'changed')
        self.assertEqual(verified_publications(self.out),[])
    def test_after_commit_failure_keeps_new_valid_generation(self):
        publish(self.root,self.out)
        def fault(stage):
            if stage=='after-commit':raise RuntimeError('interrupted after commit')
        with self.assertRaises(RuntimeError):publish(self.root,self.out,fault=fault)
        self.assertEqual([r['sequence'] for r in verified_publications(self.out)],[2,1])

if __name__=='__main__':unittest.main()
