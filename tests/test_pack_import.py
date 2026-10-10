import copy
import io
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
import zipfile
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'tools'))
import pack_import as importer
from pack_ingest import verified_publications

class ReviewedPackTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name);self.out=self.base/'library';self.pack=self.base/'pack.zip'
    def zip(self, entries):
        with zipfile.ZipFile(self.pack,'w',zipfile.ZIP_DEFLATED) as archive:
            for name,data in entries:archive.writestr(name,data)
        return self.pack
    def load(self, record):
        return json.loads((self.out/record['directory']/'catalog.json').read_text())
    def test_zip_preview_conflict_choice_and_unknown(self):
        self.zip([('A.tap',b'one'),('B.z80',b'one'),('Second.sna',b'two'),('readme.txt',b'help')])
        plan=importer.preview(self.pack,self.out)
        self.assertFalse(self.out.exists());self.assertEqual(plan,importer.preview(self.pack,self.out))
        self.assertEqual(len(plan['unresolvedFormats']),1)
        sha=plan['unresolvedFormats'][0];plan['choices'][sha]='B.z80'
        record,report=importer.import_pack(self.pack,self.out,plan)
        self.assertEqual({r['format'] for g in self.load(record)['games'] for r in g['releases']},{'z80','sna'})
        self.assertEqual(len(report['unknown']),2)
        self.assertEqual(report['source']['kind'],'zip')
    def test_additive_dedup_and_profile_preservation(self):
        self.zip([('Old.tap',b'old')]);first,_=importer.import_pack(self.pack,self.out,importer.preview(self.pack,self.out))
        profile=self.out/'profiles'/'custom.json';profile.parent.mkdir();profile.write_bytes(b'user-owned')
        self.zip([('alias.tap',b'old'),('New.tap',b'new')])
        second,report=importer.import_pack(self.pack,self.out,importer.preview(self.pack,self.out))
        self.assertEqual(len(self.load(second)['games']),2);self.assertEqual(len(report['alreadyPresent']),1)
        self.assertEqual(profile.read_bytes(),b'user-owned');self.assertEqual(report['retainedReleases'],1)
        self.assertEqual([r['sequence'] for r in verified_publications(self.out)],[2,1])
        with self.assertRaisesRegex(ValueError,'no new releases'):importer.import_pack(self.pack,self.out,importer.preview(self.pack,self.out))
    def test_stale_input_metadata_and_library(self):
        self.zip([('A.tap',b'one')]);plan=importer.preview(self.pack,self.out)
        self.zip([('A.tap',b'changed')])
        with self.assertRaisesRegex(ValueError,'changed'):importer.import_pack(self.pack,self.out,plan)
        fresh=importer.preview(self.pack,self.out)
        importer.import_pack(self.pack,self.out,fresh)
        with self.assertRaisesRegex(ValueError,'changed'):importer.import_pack(self.pack,self.out,fresh)
    def test_skip_and_invalid_choice(self):
        self.zip([('A.tap',b'one'),('B.tap',b'two')]);plan=importer.preview(self.pack,self.out)
        sha=next(iter(plan['choices']));bad=copy.deepcopy(plan);bad['choices'][sha]='other.tap'
        with self.assertRaisesRegex(ValueError,'candidate'):importer.import_pack(self.pack,self.out,bad)
        plan['choices'][sha]=None
        record,report=importer.import_pack(self.pack,self.out,plan)
        self.assertEqual(len(self.load(record)['games']),1);self.assertEqual(len(report['skipped']),1)
    def test_unsafe_zip_paths_links_and_collisions(self):
        for names in (['../escape.tap'],['/escape.tap'],['a\\b.tap'],['C:bad.tap'],['A.tap','a.tap'],['Foo/A.tap','foo/B.tap'],['a','a/b.tap']):
            with self.subTest(names=names):
                self.zip([(n,b'one') for n in names])
                with self.assertRaises(ValueError):importer.preview(self.pack,self.out)
        with zipfile.ZipFile(self.pack,'w') as archive:
            link=zipfile.ZipInfo('link.tap');link.create_system=3;link.external_attr=0o120777<<16
            archive.writestr(link,'/etc/hosts')
        with self.assertRaisesRegex(ValueError,'link'):importer.preview(self.pack,self.out)
        self.assertFalse(self.out.exists())
    def test_tar_variants_and_link_rejection(self):
        for suffix,mode in (('.tar','w'),('.tgz','w:gz'),('.tar.bz2','w:bz2'),('.tar.xz','w:xz')):
            path=self.base/('pack'+suffix)
            with tarfile.open(path,mode) as archive:
                member=tarfile.TarInfo('folder/A.tap');member.size=3;archive.addfile(member,io.BytesIO(b'one'))
            plan=importer.preview(path,self.out);self.assertEqual(len(plan['choices']),1)
        with tarfile.open(path,'w') as archive:
            member=tarfile.TarInfo('A.tap');member.type=tarfile.SYMTYPE;member.linkname='/etc/hosts';archive.addfile(member)
        with self.assertRaisesRegex(ValueError,'link'):importer.preview(path,self.out)
    def test_metadata_grouping_and_existing_metadata_conflict(self):
        import hashlib
        identity='11111111-1111-4111-8111-111111111111'
        def item(title):return {'gameId':identity,'title':title,'details':'identified edition','model':'128k','source':'user sidecar'}
        old=hashlib.sha256(b'old').hexdigest();new=hashlib.sha256(b'new').hexdigest()
        metadata={old:item('Existing')}
        self.zip([('Old.tap',b'old')])
        importer.import_pack(self.pack,self.out,importer.preview(self.pack,self.out,metadata),metadata)
        metadata[new]=item('Changed title');self.zip([('New.z80',b'new')])
        record,report=importer.import_pack(self.pack,self.out,importer.preview(self.pack,self.out,metadata),metadata)
        game=self.load(record)['games'][0]
        self.assertEqual(game['title'],'Existing');self.assertEqual(len(game['releases']),2)
        self.assertEqual(len(report['metadataConflicts']),1);self.assertFalse(report['unknown'])
    def test_damaged_zip_crc_and_nested_archive_not_imported(self):
        self.zip([('Nested.zip',b'not recursively opened'),('A.tap',b'one')])
        self.assertEqual(len(importer.preview(self.pack,self.out)['choices']),1)
        with zipfile.ZipFile(self.pack,'w',zipfile.ZIP_STORED) as archive:archive.writestr('A.tap',b'original bytes')
        raw=self.pack.read_bytes().replace(b'original bytes',b'corrupted byte')
        self.pack.write_bytes(raw)
        with self.assertRaises(zipfile.BadZipFile):importer.preview(self.pack,self.out)
        self.assertFalse(self.out.exists())
    def test_archive_bounds(self):
        self.zip([('A.tap',b'one'),('B.tap',b'two')])
        for bound,value in (('MAX_FILE',2),('MAX_TOTAL',5),('MAX_MEMBERS',1)):
            with self.subTest(bound=bound),patch.object(importer,bound,value),self.assertRaises(ValueError):importer.preview(self.pack,self.out)
    def test_total_expansion_bound_and_archive_parent_collision(self):
        self.zip([('A.tap',b'a'*1000),('B.tap',b'b'*1000)])
        with patch.object(importer,'MAX_TOTAL',1500),self.assertRaisesRegex(ValueError,'expanded size'):
            importer.preview(self.pack,self.out)
        self.zip([('a/b.tap',b'one'),('a',b'two')])
        with self.assertRaisesRegex(ValueError,'replaces directory'):importer.preview(self.pack,self.out)
    def test_change_between_preview_check_and_base_capture(self):
        self.zip([('A.tap',b'one')]);plan=importer.preview(self.pack,self.out)
        with patch.object(importer,'base_record',side_effect=[{}, {'sequence':99}]),self.assertRaisesRegex(ValueError,'library changed'):
            importer.import_pack(self.pack,self.out,plan)
        self.assertFalse(self.out.exists())
    def test_folder_and_failed_commit_preserves_library(self):
        folder=self.base/'folder';folder.mkdir();(folder/'A.tap').write_bytes(b'one')
        first,_=importer.import_pack(folder,self.out,importer.preview(folder,self.out))
        (folder/'B.tap').write_bytes(b'two');plan=importer.preview(folder,self.out)
        def fault(stage):
            if stage=='before-commit':raise RuntimeError('power loss')
        with self.assertRaises(RuntimeError):importer.import_pack(folder,self.out,plan,fault=fault)
        self.assertEqual(verified_publications(self.out)[0],first)
    def test_library_race_detected_inside_publication_lock(self):
        self.zip([('A.tap',b'one')]);plan=importer.preview(self.pack,self.out)
        actual=importer.ingest.publish
        def racing(*args,**kwargs):
            # Simulate a competing completed publication between preview and lock.
            other=self.base/'other';other.mkdir();(other/'other.tap').write_bytes(b'other')
            actual(other,self.out)
            return actual(*args,**kwargs)
        with patch.object(importer.ingest,'publish',racing),self.assertRaisesRegex(ValueError,'library changed'):
            importer.import_pack(self.pack,self.out,plan)
        self.assertEqual(verified_publications(self.out)[0]['sequence'],1)

if __name__=='__main__':unittest.main()
