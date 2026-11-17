"""Real Chromium smoke test served by the standard Python static HTTP server.

uv run --extra browser-demo python tools/browser_demo/test_browser.py
"""

import argparse
import base64
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import importlib.util
from pathlib import Path
import shutil
import threading
import wave

import numpy as np
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *_):
        pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--chromium', default=shutil.which('chromium'))
    parser.add_argument('--output', type=Path, default=ROOT / 'build/browser-tests/demo')
    parser.add_argument('--text', action='append', help='Override default texts; may be repeated')
    parser.add_argument('--expect-warning', action='store_true', help='Require a best-effort phonetic warning in page diagnostics')
    parser.add_argument('--isolated', action='store_true', help='Use the real serve.py handler with COOP/COEP')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    handler = QuietHandler
    if args.isolated:
        spec = importlib.util.spec_from_file_location('belvoice_demo_server', ROOT / 'browser_demo/serve.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        handler = type('QuietIsolatedHandler', (module.IsolatedHTTPRequestHandler,), {'log_message': lambda *_: None})
    server = ThreadingHTTPServer(('127.0.0.1', 0), partial(handler, directory=str(ROOT / 'browser_demo')))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    results, requests, errors = [], [], []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=args.chromium, headless=True)
            page = browser.new_page(viewport={'width': 1100, 'height': 1100})
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.on('request', lambda request: requests.append(request.url))
            page.on('response', lambda response: errors.append(f'HTTP {response.status}: {response.url}') if response.status >= 400 else None)
            page.on('console', lambda message: print('BROWSER:', message.type, message.text, flush=True))
            page.goto(f'http://127.0.0.1:{server.server_port}/')
            assert page.evaluate('crossOriginIsolated') == args.isolated
            texts = args.text or [
                'Прывітанне! Гэта праверка беларускага сінтэзу маўлення.',
                'Дзякуй за падтрымку! Ён адказаў.',
                '@ % + = € $ # & <3 >2',
            ]
            for index, text in enumerate(texts, 1):
                page.locator('#text').fill(text)
                page.locator('#speak').click()
                try:
                    page.wait_for_function('window.demoLastResult || window.demoError', timeout=300_000)
                    error = page.evaluate('window.demoError')
                    if error:
                        raise AssertionError(error)
                    result = page.evaluate('window.demoLastResult.metrics')
                    runtime = page.evaluate('window.demoLastResult.runtime')
                    assert runtime['crossOriginIsolated'] == args.isolated
                    if args.isolated and runtime['hardwareConcurrency'] >= 4:
                        assert runtime['numThreads'] > 1, runtime
                    result['runtime'] = runtime
                    if args.expect_warning:
                        assert 'набліжанае вымаўленне' in page.locator('#log').inner_text()
                    assert page.evaluate('window.demoLastResult.audioContextState') == 'running'
                    encoded = page.evaluate('btoa(String.fromCharCode(...window.demoLastResult.wav.slice(0,44)))')
                    assert base64.b64decode(encoded)[:4] == b'RIFF'
                    with page.expect_download() as download:
                        page.locator('#download').click()
                    output = args.output / f'browser-{index}.wav'
                    download.value.save_as(output)
                    with wave.open(str(output), 'rb') as wav:
                        assert wav.getnchannels() == 1 and wav.getframerate() == 22050 and wav.getsampwidth() == 2
                        samples = np.frombuffer(wav.readframes(wav.getnframes()), dtype='<i2')
                        assert len(samples) > 2205 and np.abs(samples.astype(float)).max() > 100
                    result.update(text=text, phonemes=page.locator('#phonemes').inner_text(), wav=str(output))
                    print('VERIFIED:', json.dumps(result, ensure_ascii=False), flush=True)
                    results.append(result)
                finally:
                    (args.output / 'page-log.txt').write_text(page.locator('#log').inner_text())
                    page.screenshot(path=str(args.output / 'page.png'), full_page=True)
            assert not errors, errors
            assert all(url.startswith(f'http://127.0.0.1:{server.server_port}/') or url.startswith('blob:') for url in requests), requests
            for name in ['encoder.onnx', 'decoder.onnx', 'vocoder.onnx', 'grammar.json.gz']:
                assert sum(url.endswith(name) for url in requests) == 1, f'{name} was reloaded'
            browser.close()
    finally:
        server.shutdown()
    # Compare downloaded browser PCM with the original, unmodified checkpoints.
    # Do this after closing Chromium to avoid keeping both runtimes in memory.
    import torch
    from belvoice.synth.tts.TTSCoquiTTS import TTSCoquiTTS

    torch.set_num_threads(2)
    synth = TTSCoquiTTS()._get_synthesizer()
    for result in results:
        ids = torch.tensor([synth.tts_model.tokenizer.text_to_ids(result['phonemes'])])
        with torch.inference_mode():
            mel = synth.tts_model.inference(ids, {'x_lengths':torch.tensor([ids.shape[1]])})['model_outputs'].transpose(1,2)
            expected = synth.vocoder_model.inference(torch.clamp(mel,-4,4)).numpy().reshape(-1)
        expected = expected * (32767/max(.01,float(np.max(np.abs(expected)))))
        with wave.open(result['wav'], 'rb') as wav:
            actual = np.frombuffer(wav.readframes(wav.getnframes()), dtype='<i2').astype(float)
        assert actual.shape == expected.shape, (actual.shape, expected.shape)
        rmse = float(np.sqrt(np.mean((actual-expected)**2)))
        correlation = float(np.corrcoef(actual, expected)[0,1])
        assert rmse/32768 < .01 and correlation > .99, (rmse, correlation)
        result.update(pcm_rmse=rmse, pcm_correlation=correlation)
        print('VERIFIED browser/PyTorch PCM:', rmse, correlation, flush=True)
    (args.output / 'report.json').write_text(json.dumps({'results':results, 'requests':requests, 'errors':errors}, ensure_ascii=False, indent=2))
    print(f'Verified: browser-only synthesis, crossOriginIsolated={args.isolated}, no external network, model reuse.')


if __name__ == '__main__':
    main()
