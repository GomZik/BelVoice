"""Real demo A/B toggle test, including lazy model loading and Python parity."""

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

ROOT=Path(__file__).resolve().parents[2]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--chromium',default=shutil.which('chromium'))
    parser.add_argument('--demo',type=Path,default=ROOT/'browser_demo',help='Static demo directory to serve.')
    parser.add_argument('--output',type=Path,default=ROOT/'build/browser-tests/stress-ml')
    args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=True)
    spec=importlib.util.spec_from_file_location('belvoice_serve',ROOT/'browser_demo/serve.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    handler=type('QuietHandler',(module.IsolatedHTTPRequestHandler,),{'log_message':lambda *_:None})
    server=ThreadingHTTPServer(('127.0.0.1',0),partial(handler,directory=str(args.demo.resolve())))
    threading.Thread(target=server.serve_forever,daemon=True).start()
    results,requests,errors=[],[],[]
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(executable_path=args.chromium,headless=True)
            page=browser.new_page()
            page.on('request',lambda request:requests.append(request.url))
            page.on('pageerror',lambda error:errors.append(str(error)))
            page.on('response',lambda response:errors.append(f'HTTP {response.status}: {response.url}') if response.status>=400 else None)
            page.goto(f'http://127.0.0.1:{server.server_port}/')
            text='Прывітанне, стрымерскі рудзі! Му́ка.'
            for mode in [False,True,False,True]:
                page.locator('#text').fill(text)
                page.locator('#use-stress-ml').set_checked(mode)
                page.locator('#speak').click()
                page.wait_for_function('window.demoLastResult || window.demoError',timeout=300_000)
                assert not page.evaluate('window.demoError'), page.locator('#log').inner_text()
                result=page.evaluate('''() => {const r=window.demoLastResult;return {normalized:r.normalized,phonemes:r.phonemes,stressML:r.stressML,metrics:r.metrics,timing:r.timing,runtime:r.runtime};}''')
                assert result['timing']['coldStart']==(not results)
                assert result['timing']['initialLoadMs']>0
                assert result['timing']['totalWaitMs']>=result['metrics']['totalMs']
                assert result['runtime']['loadMs']>=result['runtime']['modelInitMs']>0
                assert 'ініцыялізацыя ONNX/WASM' in page.locator('#load-time').inner_text()
                assert 'Вакодэр:' in page.locator('#stage-times').inner_text()
                assert 'NaN' not in page.locator('#load-time').inner_text()
                assert result['stressML']['enabled']==mode
                assert 'Му́ка' in result['normalized']
                assert 'Прывітанне,' in result['normalized'], 'ML must not override the dictionary word'
                loads=sum(url.endswith('/stress-ml.onnx') for url in requests)
                if mode:
                    assert loads==1, loads
                    assert len(result['stressML']['applied'])==2, result
                    assert 'стры́мерскі' in result['normalized'] and 'рудзі́' in result['normalized'], result
                    with page.expect_download() as download:
                        page.locator('#download').click()
                    download.value.save_as(args.output/'ml.wav')
                else:
                    assert not result['stressML']['applied']
                    assert result['normalized']==text
                    if not results: assert loads==0, 'StressML must not load when disabled'
                print('VERIFIED ML toggle:',json.dumps(result,ensure_ascii=False),flush=True)
                results.append(result)
            assert results[0]['phonemes']==results[2]['phonemes']
            assert results[1]['phonemes']==results[3]['phonemes']
            assert results[0]['phonemes']!=results[1]['phonemes']
            for name in ['encoder.onnx','decoder.onnx','vocoder.onnx','stress-ml.onnx','grammar.json.gz']:
                assert sum(url.endswith('/'+name) for url in requests)==1, name
            assert not errors,errors
            (args.output/'page-log.txt').write_text(page.locator('#log').inner_text())
            page.screenshot(path=str(args.output/'page.png'),full_page=True)
            browser.close()
    finally:
        server.shutdown();server.server_close()
    from belvoice.synth.stress.StressML import StressML
    reference=StressML()
    for result in results:
        for prediction in result['stressML']['applied']:
            word,confidence=reference.process_word(prediction['word'])
            assert word==prediction['stressed'], prediction
            np.testing.assert_allclose(confidence,prediction['confidence'],atol=2e-4)
    with wave.open(str(args.output/'ml.wav'),'rb') as wav:
        pcm=np.frombuffer(wav.readframes(wav.getnframes()),dtype='<i2')
        assert wav.getframerate()==22050 and wav.getnchannels()==1 and len(pcm)>22050 and np.any(pcm)
    (args.output/'report.json').write_text(json.dumps({'results':results,'requests':requests,'errors':errors},ensure_ascii=False,indent=2))
    print('Verified OFF/ON/OFF/ON, lazy load once, unchanged dictionary/manual stresses, Python prediction parity and real WAV.')


if __name__=='__main__':
    main()
