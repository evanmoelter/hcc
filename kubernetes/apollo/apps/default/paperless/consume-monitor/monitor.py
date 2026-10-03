from fnmatch import fnmatchcase
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import stat
import time


IGNORE_PATTERNS = (
    '.DS_Store', '.DS_STORE', '._*', '.stfolder/*', '.stversions/*',
    '.localized/*', 'desktop.ini', '@eaDir/*', 'Thumbs.db', 'lost+found/*',
)


def consume_status(root=Path('/consume'), now=None):
    now = time.time() if now is None else now
    count = 0
    oldest = now
    directories = [root]
    while directories:
        with os.scandir(directories.pop()) as entries:
            for entry in entries:
                try:
                    info = entry.stat(follow_symlinks=False)
                except FileNotFoundError:
                    continue
                is_directory = stat.S_ISDIR(info.st_mode)
                name = entry.name + '/' if is_directory else entry.name
                if any(fnmatchcase(name, pattern) for pattern in IGNORE_PATTERNS):
                    continue
                if is_directory:
                    directories.append(Path(entry.path))
                elif stat.S_ISREG(info.st_mode):
                    count += 1
                    oldest = min(oldest, info.st_mtime)
    return {'files': count, 'oldest_age_seconds': now - oldest}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/healthz':
            code, result = 200, {'healthy': True}
        elif self.path == '/status':
            try:
                code, result = 200, consume_status()
            except OSError:
                code, result = 503, {'error': 'consume scan failed'}
        else:
            code, result = 404, {'error': 'not found'}
        body = json.dumps(result).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass


if __name__ == '__main__':
    HTTPServer(('0.0.0.0', 8080), Handler).serve_forever()
