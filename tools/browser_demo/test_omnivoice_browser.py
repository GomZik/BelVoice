"""Real optional OmniVoice WASM test. Needs prepared resources and local weights.

uv run --extra browser-demo python tools/browser_demo/prepare_omnivoice.py --models wasm
uv run --extra browser-demo python tools/browser_demo/test_omnivoice_browser.py
The test uses a local mirror and never uploads text/audio or downloads weights.
"""
import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import shutil
import tempfile
import threading
import urllib.parse
import wave

import numpy as np
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]


class RangeHandler(SimpleHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def end_headers(self):
        self.send_header('Cross-Origin-Opener-Policy', 'same-origin')
        self.send_header('Cross-Origin-Embedder-Policy', 'require-corp')
        super().end_headers()

    def send_head(self):
        path = Path(self.translate_path(self.path))
        requested = self.headers.get('Range')
        if not requested or not path.is_file():
            self.remaining = None
            return super().send_head()
        match = re.fullmatch(r'bytes=(\d+)-(\d+)', requested)
        size = path.stat().st_size
        if not match:
            self.send_error(416)
            return None
        start, end = map(int, match.groups())
        end = min(end, size - 1)
        if start > end:
            self.send_error(416)
            return None
        self.send_response(206)
        self.send_header('Content-Type', self.guess_type(str(path)))
        self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
        self.send_header('Content-Length', str(end - start + 1))
        self.send_header('Accept-Ranges', 'bytes')
        self.end_headers()
        stream = path.open('rb')
        stream.seek(start)
        self.remaining = end - start + 1
        return stream

    def copyfile(self, source, outputfile):
        if self.remaining is None:
            return super().copyfile(source, outputfile)
        while self.remaining:
            chunk = source.read(min(self.remaining, 1024 * 1024))
            if not chunk:
                break
            outputfile.write(chunk)
            self.remaining -= len(chunk)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--demo', type=Path, default=ROOT / 'browser_demo')
    parser.add_argument('--models', type=Path, default=ROOT / 'models/omnivoice-browser')
    parser.add_argument('--output', type=Path, default=ROOT / 'build/browser-tests/omnivoice')
    parser.add_argument('--chromium', default=shutil.which('chromium'))
    parser.add_argument('--text', default='Так.')
    parser.add_argument('--steps', type=int, default=8)
    parser.add_argument('--stress-ml', action='store_true', help='Add StressStat/StressML accents to OmniVoice input text.')
    parser.add_argument('--backend', choices=['wasm','webgpu'], default='wasm')
    parser.add_argument('--probe-only', action='store_true', help='Check consent/UI and unsupported WebGPU without loading large weights.')
    args = parser.parse_args()
    if not args.probe_only:
        required = 'omnivoice-main-split.onnx' if args.backend == 'wasm' else 'engine/omnivoice-f16.bin'
        assert (args.models / required).is_file(), f'Prepare --models {args.backend} first'
    args.output.mkdir(parents=True, exist_ok=True)
    requests, errors, console, results = [], [], [], []
    with tempfile.TemporaryDirectory(prefix='belvoice-omni-host-') as temp:
        stage = Path(temp)
        (stage / 'demo').symlink_to(args.demo.resolve(), target_is_directory=True)
        (stage / 'omni-models').symlink_to(args.models.resolve(), target_is_directory=True)
        server = ThreadingHTTPServer(('127.0.0.1', 0), partial(RangeHandler, directory=str(stage)))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(executable_path=args.chromium, headless=True, args=['--disable-dev-shm-usage'])
                page = browser.new_page()
                page.on('crash', lambda: errors.append('Chromium renderer crashed (possibly memory pressure).'))
                page.on('request', lambda r: requests.append(r.url))
                page.on('pageerror', lambda e: errors.append(str(e)))
                page.on('console', lambda m: console.append(f'{m.type}: {m.text}'))
                page.on('response', lambda r: errors.append(f'HTTP {r.status}: {r.url}') if r.status >= 400 else None)
                base = f'http://127.0.0.1:{server.server_port}'
                page.goto(base + '/demo/?omniModels=/omni-models')
                page.expose_function('benchmarkEvent', lambda text: print('OMNI:', text, flush=True))
                page.evaluate('''() => {
                  new MutationObserver(() => {
                    const lines=document.getElementById('log').textContent.trim().split('\\n');
                    window.benchmarkEvent(lines.at(-1));
                  }).observe(document.getElementById('log'),{childList:true,characterData:true,subtree:true});
                }''')
                page.locator('#voice').select_option('omnivoice')
                page.locator('#omni-backend').select_option('webgpu' if args.probe_only else args.backend)
                page.locator('#omni-steps').select_option(str(args.steps))
                page.locator('#text').fill(args.text)
                page.locator('#use-stress-ml').set_checked(args.stress_ml)
                page.locator('#speak').click()
                assert 'Пацвердзіце' in page.locator('#status').inner_text()
                assert not any('/omni-models/' in url for url in requests), 'No model requests before consent'
                assert page.locator('#use-stress-ml').is_enabled()
                if args.probe_only:
                    capable = page.evaluate("async()=>{const a=await navigator.gpu?.requestAdapter();return !!a?.features.has('shader-f16');}")
                    if not capable:
                        page.locator('#omni-consent').check()
                        page.locator('#speak').click()
                        page.wait_for_function('window.demoError', timeout=60_000)
                        assert 'shader-f16 is required' in page.evaluate('window.demoError')
                        assert not any('/omni-models/' in url for url in requests), 'Unsupported WebGPU must not load WASM weights'
                    (args.output/'probe.json').write_text(json.dumps({'webgpuCapable':capable,'requests':requests,'errors':errors},indent=2))
                    assert not errors,errors
                    print('VERIFIED consent gate; WebGPU capable:',capable,'; no weight downloads or automatic WASM fallback.',flush=True)
                    browser.close()
                    return
                page.locator('#omni-consent').check()
                page.locator('#speak').click()
                try:
                    page.wait_for_function('window.demoLastResult || window.demoError', timeout=1_200_000)
                    assert not page.evaluate('window.demoError'), page.locator('#log').inner_text()
                    result = page.evaluate('''() => {const r=window.demoLastResult;return {runtime:r.runtime,metrics:r.metrics,normalized:r.normalized,stressML:r.stressML,timing:r.timing};}''')
                    assert result['runtime']['backend'] == args.backend
                    assert result['runtime']['voice'] == 'omnivoice'
                    assert result['metrics']['steps'] == args.steps
                    assert result['metrics']['sampleRate'] == 24000
                    assert result['stressML']['enabled'] == args.stress_ml
                    with page.expect_download() as download:
                        page.locator('#download').click()
                    download.value.save_as(args.output / 'omnivoice.wav')
                    with wave.open(str(args.output / 'omnivoice.wav'), 'rb') as wav:
                        pcm = np.frombuffer(wav.readframes(wav.getnframes()), dtype='<i2')
                        assert wav.getframerate() == 24000 and wav.getnchannels() == 1
                        assert len(pcm) > 2400 and np.any(pcm)
                    assert not any('encoder-fixed' in url or 'whisper' in url for url in requests)
                    assert all(url.startswith(base) or url.startswith('blob:') for url in requests)
                    assert not errors, errors
                    results.append(result)
                    print('VERIFIED OmniVoice:', json.dumps(result, ensure_ascii=False), flush=True)
                finally:
                    (args.output / 'console.txt').write_text('\n'.join(console))
                    (args.output / 'report.json').write_text(json.dumps({'results': results, 'requests': requests, 'errors': errors}, ensure_ascii=False, indent=2))
                    try:
                        (args.output / 'log.txt').write_text(page.locator('#log').inner_text(timeout=5000))
                        page.screenshot(path=str(args.output / 'page.png'), full_page=True, timeout=5000)
                    except Exception as error:
                        (args.output / 'page-failure.txt').write_text(str(error))
                    browser.close()
        finally:
            server.shutdown()
            server.server_close()


if __name__ == '__main__':
    main()
