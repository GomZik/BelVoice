"""Local static demo server with headers required for multithreaded WASM.

python browser_demo/serve.py
No dependencies; no text/audio processing happens on this server.
"""

import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys


class IsolatedHTTPRequestHandler(SimpleHTTPRequestHandler):
    extensions_map = {
        **SimpleHTTPRequestHandler.extensions_map,
        '.js': 'text/javascript',
        '.mjs': 'text/javascript',
        '.wasm': 'application/wasm',
    }

    def end_headers(self):
        # Also apply to Worker/module responses, not just index.html.
        self.send_header('Cross-Origin-Opener-Policy', 'same-origin')
        self.send_header('Cross-Origin-Embedder-Policy', 'require-corp')
        # This is a development/recording server: don't keep an older Worker
        # or script from a previous demo build in the browser cache.
        self.send_header('Cache-Control', 'no-store')
        super().end_headers()


def create_server(directory=None, bind='127.0.0.1', port=8000):
    directory = Path(directory) if directory is not None else Path(__file__).resolve().parent
    if not directory.is_dir():
        raise ValueError(f'Каталог не існуе: {directory}')
    handler = partial(IsolatedHTTPRequestHandler, directory=str(directory.resolve()))
    return ThreadingHTTPServer((bind, port), handler)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Статычны сервер BelVoice з падтрымкай шматпаточнага WASM.')
    parser.add_argument('--port', type=int, default=8000, help='Порт (8000)')
    parser.add_argument('--bind', default='127.0.0.1', help='Адрас (127.0.0.1; лакальны доступ)')
    parser.add_argument('--directory', type=Path, default=Path(__file__).resolve().parent,
                        help='Статычная папка (па змаўчанні browser_demo побач са скрыптам)')
    args = parser.parse_args(argv)
    if not 0 <= args.port <= 65535:
        parser.error('Порт мусіць быць у дыяпазоне 0–65535')
    try:
        server = create_server(args.directory, args.bind, args.port)
    except (OSError, ValueError) as error:
        print(f'Не атрымалася запусціць сервер: {error}', file=sys.stderr)
        return 1
    with server:
        host = 'localhost' if args.bind in ('127.0.0.1', '0.0.0.0') else args.bind
        print(f'BelVoice: http://{host}:{server.server_port}', flush=True)
        print(f'Папка: {args.directory.resolve()}', flush=True)
        print('COOP/COEP уключаныя. Адкрыйце старонку і націсніце «Агучыць». Ctrl+C — спыніць.', flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
    return 0


if __name__ == '__main__':
    sys.exit(main())
