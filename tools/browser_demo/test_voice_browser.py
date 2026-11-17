"""Exercise real default/female voice switching and WAV output in Chromium."""
import argparse
from functools import partial
from http.server import ThreadingHTTPServer
import importlib.util
import json
from pathlib import Path
import shutil
import threading
import wave

import numpy as np
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--demo', type=Path, default=ROOT / 'browser_demo')
    parser.add_argument('--output', type=Path, default=ROOT / 'build/browser-tests/voices')
    parser.add_argument('--chromium', default=shutil.which('chromium'))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    spec = importlib.util.spec_from_file_location('serve', ROOT / 'browser_demo/serve.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    handler = type('QuietHandler', (module.IsolatedHTTPRequestHandler,), {'log_message': lambda *_: None})
    server = ThreadingHTTPServer(('127.0.0.1', 0), partial(handler, directory=str(args.demo.resolve())))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    requests, errors, results = [], [], []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=args.chromium, headless=True)
            page = browser.new_page()
            page.on('request', lambda request: requests.append(request.url))
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.on('response', lambda r: errors.append(f'HTTP {r.status}: {r.url}') if r.status >= 400 else None)
            page.goto(f'http://127.0.0.1:{server.server_port}/')
            assert not any('/models/' in url for url in requests)
            for index, (voice, ml, speed) in enumerate([('default', True, 1), ('female-1', True, 1), ('female-1', True, 1.35), ('female-1', False, 1.35), ('default', True, 1)]):
                if page.locator('#voice').input_value() != voice:
                    page.locator('#voice').select_option(voice)
                page.locator('#text').fill('Прывітанне, стрымерскі рудзі! Му́ка. Слімак.')
                page.locator('#use-stress-ml').set_checked(ml)
                page.locator('#speed').fill(str(speed))
                assert page.locator('#speed-value').inner_text() == f'{speed:.2f}×'
                before = len(requests)
                page.locator('#speak').click()
                page.wait_for_function('window.demoLastResult || window.demoError', timeout=300_000)
                assert not page.evaluate('window.demoError'), page.locator('#log').inner_text()
                result = page.evaluate('''() => {const r=window.demoLastResult; return {runtime:r.runtime,metrics:r.metrics,timing:r.timing,normalized:r.normalized,phonemes:r.phonemes,stressML:r.stressML};}''')
                assert result['runtime']['voice'] == voice
                assert result['stressML']['enabled'] == ml
                assert result['timing']['coldStart'] == (index in [0, 1, 4])
                assert result['metrics']['speed'] == speed
                assert page.locator('#audio').evaluate('(audio)=>audio.playbackRate') == 1
                assert not page.locator('#voice').is_disabled()
                if index == 0:
                    assert not any('/female-1/' in url for url in requests)
                if index in [2, 3]:
                    assert not [url for url in requests[before:] if url.startswith('http')], 'Warm synthesis must not reload assets'
                with page.expect_download() as download:
                    page.locator('#download').click()
                wav_path = args.output / f'{index}-{voice}.wav'
                download.value.save_as(wav_path)
                with wave.open(str(wav_path), 'rb') as wav:
                    pcm = np.frombuffer(wav.readframes(wav.getnframes()), dtype='<i2')
                    assert wav.getframerate() == 22050 and wav.getnchannels() == 1
                    assert pcm.size > 22050 and np.any(pcm)
                results.append(result)
                # Reset test sentinel even when selecting the same option next time.
                page.evaluate('window.demoLastResult=null')
                print('VERIFIED', voice, ml, result['metrics'], flush=True)
            assert results[0]['phonemes'] == results[1]['phonemes'] == results[2]['phonemes'] == results[4]['phonemes']
            assert results[2]['metrics']['frames'] < results[1]['metrics']['frames']
            assert results[2]['metrics']['duration'] < results[1]['metrics']['duration']
            assert results[0]['metrics']['frames'] != results[1]['metrics']['frames']
            assert not errors, errors
            page.screenshot(path=str(args.output / 'page.png'), full_page=True)
            (args.output / 'log.txt').write_text(page.locator('#log').inner_text())
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
    (args.output / 'report.json').write_text(json.dumps({'results': results, 'requests': requests, 'errors': errors}, ensure_ascii=False, indent=2))
    print('Verified voice switching, lazy assets, warm reuse, StressML and real WAVs.')


if __name__ == '__main__':
    main()
