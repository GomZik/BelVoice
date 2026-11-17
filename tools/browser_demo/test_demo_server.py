"""Standard-library tests for the real local demo server."""

import http.client
import importlib.util
from pathlib import Path
import threading
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('belvoice_demo_server', ROOT / 'browser_demo/serve.py')
server_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server_module)


class DemoServerTests(unittest.TestCase):
    def test_static_files_headers_and_mime_types(self):
        with server_module.create_server(port=0) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                for path, mime, status in [
                    ('/', 'text/html', 200), ('/worker.js', 'text/javascript', 200),
                    ('/vendor/ort-wasm-simd-threaded.mjs', 'text/javascript', 200),
                    ('/vendor/ort-wasm-simd-threaded.wasm', 'application/wasm', 200),
                    ('/not-found', 'text/html', 404),
                ]:
                    with self.subTest(path=path):
                        connection = http.client.HTTPConnection('127.0.0.1', server.server_port)
                        try:
                            connection.request('HEAD', path)
                            response = connection.getresponse()
                            self.assertEqual(response.status, status)
                            self.assertEqual(response.getheader('Cross-Origin-Opener-Policy'), 'same-origin')
                            self.assertEqual(response.getheader('Cross-Origin-Embedder-Policy'), 'require-corp')
                            self.assertEqual(response.getheader('Cache-Control'), 'no-store')
                            self.assertTrue(response.getheader('Content-Type').startswith(mime))
                        finally:
                            connection.close()
            finally:
                server.shutdown()
                thread.join()


if __name__ == '__main__':
    unittest.main()
