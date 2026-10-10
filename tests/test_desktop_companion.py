import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import zipfile
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from desktop_companion import Session, serve, TARGET
import pack_ingest


class CompanionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.card = self.root / 'card'; self.card.mkdir()
        self.source = self.root / 'games'; self.source.mkdir()
        (self.source / 'First.tap').write_bytes(b'nonplayable integration fixture')
        self.session = Session(picker=lambda kind: self.card if kind == 'card' else self.source)
        self.session.dispatch('pick', {'kind':'card'})
        self.session.dispatch('pick', {'kind':'folder'})

    def tearDown(self):
        self.temp.cleanup()

    def test_real_first_and_additive_import_preserves_presets(self):
        self.assertFalse((self.card / TARGET).exists())
        result = self.session.dispatch('preview', {'model':'128k'})
        self.assertFalse((self.card / TARGET).exists())
        result = self.session.dispatch('import', {'choices':result['plan']['choices']})
        self.assertEqual(result['generation'], 1)
        preset = self.card / TARGET / 'profiles' / 'user.json'
        preset.parent.mkdir(); preset.write_text('user owned')
        (self.source / 'Second.z80').write_bytes(b'second fixture')
        preview = self.session.dispatch('preview', {'model':'48k'})
        self.assertEqual(len(preview['existing']), 1)
        result = self.session.dispatch('import', {'choices':preview['plan']['choices']})
        self.assertEqual(result['generation'], 2)
        self.assertEqual(preset.read_text(), 'user owned')
        self.assertEqual(len(result['report']['included']), 1)

    def test_macos_metadata_is_not_a_game(self):
        (self.source / '._First.tap').write_bytes(b'Finder metadata')
        result = self.session.dispatch('preview', {'model':'48k'})
        self.assertEqual(len(result['plan']['candidates']), 1)
        self.assertEqual(result['plan']['report']['excluded'][0]['reason'], 'macOS metadata sidecar')

    def test_zip_and_format_decision(self):
        archive = self.root / 'pack.zip'
        with zipfile.ZipFile(archive, 'w') as z:
            z.writestr('One.tap', b'bytes'); z.writestr('Other.z80', b'bytes')
        self.session.source = archive
        preview = self.session.dispatch('preview', {'model':'48k'})
        self.assertEqual(len(preview['plan']['unresolvedFormats']), 1)
        sha = next(iter(preview['plan']['choices']))
        result = self.session.dispatch('import', {'choices':{sha:'One.tap'}})
        self.assertEqual(result['generation'], 1)

    def test_stale_review_and_invalid_choice(self):
        preview = self.session.dispatch('preview', {'model':'48k'})
        sha = next(iter(preview['plan']['choices']))
        with self.assertRaisesRegex(ValueError, 'listed release'):
            self.session.dispatch('import', {'choices':{sha:'../outside.tap'}})
        (self.source / 'First.tap').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'changed'):
            self.session.dispatch('import', {'choices':preview['plan']['choices']})
        self.assertFalse((self.card / TARGET).exists())

    def test_generated_source_and_root_rejected(self):
        self.session.source = self.card
        with self.assertRaisesRegex(ValueError, 'original games'):
            self.session.dispatch('preview', {'model':'48k'})
        self.session.source = self.card / TARGET
        self.session.source.mkdir(parents=True)
        with self.assertRaisesRegex(ValueError, 'original games'):
            self.session.dispatch('preview', {'model':'48k'})

    def test_unsafe_archive_and_symlink_rejected(self):
        archive = self.root / 'bad.zip'
        with zipfile.ZipFile(archive, 'w') as z: z.writestr('../escape.tap', b'bytes')
        self.session.source = archive
        with self.assertRaises(ValueError): self.session.dispatch('preview', {'model':'48k'})
        linked = self.root / 'linked'; linked.symlink_to(self.source, target_is_directory=True)
        self.session.source = linked
        with self.assertRaisesRegex(ValueError, 'symbolic link'): self.session.dispatch('preview', {'model':'48k'})
        self.assertFalse((self.card / TARGET).exists())

    def test_cancel_and_empty_pack(self):
        self.session.picker = lambda _: None
        self.assertTrue(self.session.dispatch('pick', {'kind':'folder'})['cancelled'])
        (self.source / 'First.tap').unlink()
        result = self.session.dispatch('preview', {'model':'48k'})
        self.assertEqual(result['plan']['candidates'], {})
        with self.assertRaisesRegex(ValueError, 'no new releases'):
            self.session.dispatch('import', {'choices':{}})
        self.assertFalse((self.card / TARGET).exists())

    def test_local_http_security_and_real_api(self):
        server = serve(self.session)
        worker = threading.Thread(target=server.serve_forever); worker.start()
        url = f'http://127.0.0.1:{server.server_port}'
        def request(route, body=None, **headers):
            data = json.dumps(body).encode() if body is not None else None
            h = {'Content-Type':'application/json', 'X-SpectrumDeck-Token':self.session.token, **headers}
            return urllib.request.urlopen(urllib.request.Request(url+route, data=data, headers=h), timeout=5)
        try:
            self.assertIn(b'DESKTOP COMPANION', request('/').read())
            self.assertIn(b'Preview pack', request('/app.js').read())
            with self.assertRaises(urllib.error.HTTPError) as e: request('/api/state', {}, **{'X-SpectrumDeck-Token':'bad'})
            self.assertEqual(e.exception.code, 403)
            with self.assertRaises(urllib.error.HTTPError) as e: request('/api/state', {}, Origin='https://evil.example')
            self.assertEqual(e.exception.code, 403)
            with self.assertRaises(urllib.error.HTTPError) as e: request('/api/state', {}, Host='evil.example')
            self.assertEqual(e.exception.code, 403)
            with self.assertRaises(urllib.error.HTTPError) as e: request('/tools/desktop_companion.py')
            self.assertEqual(e.exception.code, 404)
            self.session.lock.acquire()
            try:
                with self.assertRaises(urllib.error.HTTPError) as e: request('/api/state', {})
                self.assertEqual(e.exception.code, 409)
            finally: self.session.lock.release()
            preview = json.load(request('/api/preview', {'model':'48k'}))
            result = json.load(request('/api/import', {'choices':preview['plan']['choices']}))
            self.assertEqual(result['generation'], 1)
            self.assertEqual(pack_ingest.verified_publications(self.card / TARGET)[0]['sequence'], 1)
        finally:
            server.shutdown(); server.server_close(); worker.join()

if __name__ == '__main__': unittest.main()
