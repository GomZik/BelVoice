"""Real browser StressML + OmniVoice adapter test, without large TTS weights.

Only the diffusion Worker is stubbed. The text Worker, WASM runtime,
StressStat, StressML inference and forwarding of accented text are real.
"""
import argparse
from functools import partial
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import shutil
import threading

from playwright.sync_api import sync_playwright
from test_omnivoice_browser import RangeHandler, ROOT


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--demo', type=Path, default=ROOT / 'browser_demo')
    parser.add_argument('--chromium', default=shutil.which('chromium'))
    args = parser.parse_args()
    server = ThreadingHTTPServer(('127.0.0.1', 0), partial(RangeHandler, directory=str(args.demo.resolve())))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=args.chromium, headless=True, args=['--disable-dev-shm-usage'])
            try:
                page = browser.new_page()
                requests, errors = [], []
                page.on('request', lambda r: requests.append(r.url))
                page.on('pageerror', lambda e: errors.append(str(e)))
                page.on('response', lambda r: errors.append(f'HTTP {r.status}: {r.url}') if r.status >= 400 else None)
                page.goto(f'http://127.0.0.1:{server.server_port}/index.html')
                result = page.evaluate('''async()=>{
                  const NativeWorker=globalThis.Worker, sent=[], logs=[];
                  globalThis.Worker=class {
                    constructor(url,options){
                      if(!String(url).endsWith('/omnivoice-worker.js')) return new NativeWorker(url,options);
                    }
                    postMessage(data){
                      if(data.type==='init') queueMicrotask(()=>this.onmessage({data:{type:'ready',backend:'cpu'}}));
                      else {
                        sent.push(data.text);
                        queueMicrotask(()=>this.onmessage({data:{type:'audio',jobId:data.jobId,pcm:new Float32Array([0,0.1]),sampleRate:24000}}));
                      }
                    }
                    terminate(){}
                  };
                  const {createBelVoice}=await import('./belvoice.js');
                  const engine=createBelVoice({voice:'omnivoice',backend:'wasm',allowModelDownload:true,onLog:s=>logs.push(s)});
                  try {
                    const known=await engine.synthesize('Прывітанне! Малако, ёлка, абраза.',{useStressML:true});
                    const knownLoadedML=logs.some(s=>s.includes('StressML загружаная'));
                    const first=await engine.synthesize('Ультракрыптавалюта, ма́ма: 1000.',{useStressML:true});
                    const second=await engine.synthesize('Ультракрыптавалюта.',{useStressML:true});
                    const plain=await engine.synthesize('1000',{useStressML:false});
                    return {sent,logs,knownLoadedML,known:{normalized:known.normalized,stressML:known.stressML},
                      first:{normalized:first.normalized,stressML:first.stressML,ms:first.metrics.stressMlMs},
                      second:{stressML:second.stressML,ms:second.metrics.stressMlMs},plain:{normalized:plain.normalized,stressML:plain.stressML}};
                  } finally {engine.dispose();globalThis.Worker=NativeWorker;}
                }''')
                assert not errors, errors
                assert result['known']['normalized'] == 'Прывіта́нне! Малако́, ё́лка, абра́за.'
                assert result['known']['stressML']['stageCounts'] == {'usual':2,'dictionary':1,'statistical':1,'ml':0}
                assert result['knownLoadedML'] is False, 'Known words must not load StressML'
                assert result['sent'][1] == result['first']['normalized']
                assert 'ма́ма' in result['sent'][1], 'Manual accent must survive'
                assert 'адна тысяча' in result['sent'][1].replace('\u0301', ''), 'Numbers normalized before inference'
                applied = result['first']['stressML']['applied']
                assert any(p['word'] == 'Ультракрыптавалюта' and '\u0301' in p['stressed'] for p in applied), applied
                assert result['plain']['normalized'] == 'адна тысяча'
                assert result['plain']['stressML']['enabled'] is False
                assert sum('StressML загружаная' in log for log in result['logs']) == 1
                assert sum('/models/stress-ml.onnx' in url for url in requests) == 1
                assert sum('/data/stresses-nohomographs.json.gz' in url for url in requests) == 1
                assert not any('/g2p/' in url or any(f'/models/{name}.onnx' in url for name in ['encoder','decoder','vocoder']) for url in requests)
                assert not any('huggingface.co' in url for url in requests), 'No large model downloads'
                print('VERIFIED real StressML, caching, manual accents, number normalization and forwarding to OmniVoice:', json.dumps(result, ensure_ascii=False))
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()


if __name__ == '__main__':
    main()
