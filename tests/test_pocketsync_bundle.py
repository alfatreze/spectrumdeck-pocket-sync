import json
from pathlib import Path
import sys
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'tools'))
from pack_import import preview,import_pack
from pack_ingest import verified_publications
from pocketsync_bundle import prepare,TARGET
class BundleTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.base=Path(self.tmp.name);self.pack=self.base/'pack';self.pack.mkdir();self.library=self.base/'library';self.bundle=self.base/'bundle'
  (self.pack/'Game.tap').write_bytes(b'original non-playable test bytes')
 def test_first_bundle_does_not_publish_to_card(self):
  result=prepare(self.pack,self.library,preview(self.pack,self.library),self.bundle)
  self.assertFalse(self.library.exists());self.assertEqual(result['expectedPrior'],{});self.assertEqual(result['target'],TARGET)
  (self.bundle/'publication-a.json').write_text(json.dumps(result['publication']))
  self.assertEqual(verified_publications(self.bundle)[0],result['publication'])
 def test_additive_bundle_preserves_prior_and_profiles(self):
  prior,_=import_pack(self.pack,self.library,preview(self.pack,self.library));profile=self.library/'custom.json';profile.write_bytes(b'user-owned')
  (self.pack/'Second.z80').write_bytes(b'another original non-playable test')
  result=prepare(self.pack,self.library,preview(self.pack,self.library),self.bundle)
  self.assertEqual(result['expectedPrior'],prior);self.assertEqual(result['publication']['sequence'],2)
  self.assertEqual(result['summary'],{'added':1,'retained':1,'unidentified':1})
  self.assertEqual(verified_publications(self.library)[0],prior);self.assertEqual(profile.read_bytes(),b'user-owned')
 def test_stale_preview_and_existing_output_rejected(self):
  plan=preview(self.pack,self.library);(self.pack/'Game.tap').write_bytes(b'changed')
  with self.assertRaises(ValueError):prepare(self.pack,self.library,plan,self.bundle)
  self.assertFalse(self.bundle.exists())
  self.bundle.mkdir()
  with self.assertRaises(ValueError):prepare(self.pack,self.library,preview(self.pack,self.library),self.bundle)
if __name__=='__main__':unittest.main()
