#!/usr/bin/env python3
"""Local graphical pack importer. No network downloads or Pocket Sync host patches."""
import argparse
import copy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import subprocess
import threading
from urllib.parse import urlsplit
import webbrowser
import catalog
import pack_import

ROOT = Path(__file__).resolve().parents[1]
TARGET = Path('Assets/spectrumdeck/common/library')


def real_directory(path):
    path = Path(path).absolute()
    for ancestor in [path, *path.parents]:
        if ancestor.is_symlink():
            raise ValueError('Choose a real folder, not a symbolic link.')
    if not path.is_dir():
        raise ValueError('The selected folder is no longer available.')
    return path


class Session:
    def __init__(self, picker=None):
        self.card = None
        self.source = None
        self.plan = None
        self.model = '48k'
        self.result = None
        self.token = secrets.token_urlsafe(32)
        self.lock = threading.Lock()
        self.picker = picker or self.native_picker
        self.cards = {}

    @staticmethod
    def native_picker(kind):
        command = 'choose file' if kind == 'archive' else 'choose folder'
        prompt = {'card': 'Select the root of your Pocket SD card', 'folder': 'Select a folder of Spectrum games', 'archive': 'Select a local ZIP or TAR pack'}[kind]
        script = 'on run argv\nreturn POSIX path of (' + command + ' with prompt (item 1 of argv))\nend run'
        result = subprocess.run(['osascript', '-e', script, prompt], capture_output=True, text=True)
        if result.returncode:
            if '(-128)' in result.stderr:
                return None
            raise ValueError('The file picker could not open. ' + result.stderr.strip())
        return Path(result.stdout.strip())

    def suggestions(self):
        self.cards = {}
        volumes = Path('/Volumes')
        if volumes.is_dir():
            for path in sorted(volumes.iterdir()):
                if not path.is_symlink() and path.is_dir() and all((path / name).is_dir() for name in ['Assets', 'Cores', 'Platforms']):
                    self.cards[str(len(self.cards))] = path
        return [{'id': key, 'name': path.name} for key, path in self.cards.items()]

    def output(self):
        if self.card is None:
            raise ValueError('Select your Pocket card first.')
        card = real_directory(self.card)
        output = card / TARGET
        for ancestor in [output, *output.parents]:
            if ancestor.is_symlink():
                raise ValueError('The library path contains a symbolic link.')
        return output

    def info(self):
        prior = pack_import.base_record(self.output()) if self.card else {}
        return {'card': str(self.card) if self.card else None,
                'source': str(self.source) if self.source else None,
                'generation': prior.get('sequence', 0), 'result': self.result}

    def select_card(self, path):
        self.card = real_directory(path)
        self.plan = None
        self.result = None
        return self.info()

    def bound_source(self):
        if not self.source:
            raise ValueError('Choose a local game folder or archive.')
        path = Path(self.source)
        for ancestor in [path, *path.parents]:
            if ancestor.is_symlink():
                raise ValueError('Source path contains a symbolic link.')
        output = self.output()
        if not path.exists() or path == self.card or path.is_relative_to(output) or output.is_relative_to(path):
            raise ValueError('Choose original games outside the generated library, not the whole card.')
        if path.is_dir():
            count = total = 0
            import os
            for folder, dirs, files in os.walk(path, followlinks=False):
                dirs[:] = [d for d in dirs if not (Path(folder) / d).is_symlink()]
                if len(Path(folder).relative_to(path).parts) > 32:
                    raise ValueError('Source exceeds the folder depth limit (32).')
                count += len(dirs) + len(files)
                if count > 100000:
                    raise ValueError('Source exceeds the entry limit (100,000).')
                for name in files:
                    item = Path(folder) / name
                    if item.is_symlink() or item.suffix.lower().lstrip('.') not in catalog.FORMATS:
                        continue
                    import stat
                    size = item.stat()
                    if not stat.S_ISREG(size.st_mode):
                        raise ValueError('Source contains a special media file.')
                    if size.st_size > 256 * 1024 * 1024:
                        raise ValueError('Media file exceeds 256 MiB.')
                    total += size.st_size
                    if total > 2 * 1024 * 1024 * 1024:
                        raise ValueError('Source media exceeds 2 GiB.')
        return path

    def dispatch(self, action, data):
        if action == 'state':
            return {**self.info(), 'cards': self.suggestions()}
        if action == 'card':
            key = data.get('id')
            if key not in self.cards:
                raise ValueError('Refresh the available cards and select again.')
            return self.select_card(self.cards[key])
        if action == 'pick':
            kind = data.get('kind')
            if kind not in ('card', 'folder', 'archive'):
                raise ValueError('Unknown picker.')
            path = self.picker(kind)
            if path is None:
                return {**self.info(), 'cancelled': True}
            if kind == 'card':
                return self.select_card(path)
            self.source = path
            self.plan = None
            self.result = None
            return self.info()
        if action == 'preview':
            self.plan = None
            model = data.get('model')
            if model not in ('48k', '128k', 'pentagon'):
                raise ValueError('Choose a Spectrum model.')
            source = self.bound_source()
            plan = pack_import.preview(source, self.output(), default_model=model)
            prior = pack_import.base_record(self.output())
            self.plan = plan
            self.model = model
            known = set(prior.get('files', {}).values())
            return {'plan': plan, 'existing': [sha for sha in plan['candidates'] if sha in known], **self.info()}
        if action == 'import':
            if self.plan is None:
                raise ValueError('Preview your pack before importing.')
            choices = data.get('choices')
            if not isinstance(choices, dict) or set(choices) != set(self.plan['candidates']):
                raise ValueError('Release choices do not match this preview.')
            for sha, choice in choices.items():
                if choice is not None and choice not in self.plan['candidates'][sha]:
                    raise ValueError('Choose a listed release file or skip it.')
            plan = copy.deepcopy(self.plan)
            plan['choices'] = choices
            record, report = pack_import.import_pack(self.bound_source(), self.output(), plan, default_model=self.model)
            self.plan = None
            self.result = {'generation': record['sequence'], 'report': report}
            return self.result
        raise ValueError('Unknown companion action.')


def serve(session, port=0):
    assets = {'/': ROOT / 'design/desktop-companion/index.html',
              '/app.js': ROOT / 'design/desktop-companion/app.js',
              '/style.css': ROOT / 'design/desktop-companion/style.css'}
    fonts = ROOT / 'design/typography/editable-fonts'
    for name in ['SpectrumDeck-Tamzen-7x14-Regular.ttf', 'SpectrumDeck-Tamzen-7x14-Bold.ttf', 'SpectrumDeck-Tamzen-10x20-Bold.ttf', 'DepartureMono-Regular.otf']:
        assets['/typography/editable-fonts/' + name] = fonts / name

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def send(self, status, payload, mime='application/json'):
            if mime == 'application/json':
                payload = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header('Content-Type', mime)
            self.send_header('Content-Length', str(len(payload)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Content-Security-Policy', "default-src 'self'; style-src 'self'; script-src 'self'; font-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'")
            self.end_headers()
            self.wfile.write(payload)

        def trusted(self):
            expected = f'127.0.0.1:{self.server.server_port}'
            return self.headers.get('Host') == expected and self.headers.get('Origin', 'http://' + expected) == 'http://' + expected

        def do_GET(self):
            if not self.trusted():
                return self.send(403, {'error': 'Invalid local origin.'})
            path = urlsplit(self.path).path
            asset = assets.get(path)
            if not asset:
                return self.send(404, {'error': 'Not found.'})
            mime = {'.html': 'text/html; charset=utf-8', '.js': 'text/javascript', '.css': 'text/css', '.ttf': 'font/ttf', '.otf': 'font/otf'}[asset.suffix]
            self.send(200, asset.read_bytes(), mime)

        def do_POST(self):
            if not self.trusted() or not secrets.compare_digest(self.headers.get('X-SpectrumDeck-Token', ''), session.token):
                return self.send(403, {'error': 'Reopen the companion from its launcher.'})
            if self.headers.get('Content-Type') != 'application/json':
                return self.send(400, {'error': 'JSON request required.'})
            if not session.lock.acquire(blocking=False):
                return self.send(409, {'error': 'Another operation is in progress. Please wait.'})
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 16 * 1024 * 1024:
                    raise ValueError('Invalid request size.')
                data = json.loads(self.rfile.read(length))
                if not isinstance(data, dict):
                    raise ValueError('Invalid request.')
                path = urlsplit(self.path).path
                if not path.startswith('/api/'):
                    raise ValueError('Unknown endpoint.')
                result = session.dispatch(path[5:], data)
                self.send(200, result)
            except Exception as error:
                # Re-read after failure: a commit may have succeeded before a response failed.
                try:
                    generation = session.info()['generation']
                except Exception:
                    generation = None
                self.send(400, {'error': str(error), 'generation': generation})
            finally:
                session.lock.release()

    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    server.daemon_threads = False  # Wait for an in-flight import when the launcher closes.
    return server


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()
    session = Session()
    server = serve(session)
    url = f'http://127.0.0.1:{server.server_port}/#{session.token}'
    print('SpectrumDeck companion is running. Close this terminal or press Ctrl-C to stop.')
    print(url)
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
