"""Sequential real MOSS browser smoke test; serves only local prepared assets."""
import argparse
from functools import partial
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import shutil
import threading
import wave

import numpy as np
from playwright.sync_api import sync_playwright
from test_omnivoice_browser import ROOT, RangeHandler


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--demo',type=Path,default=ROOT/'browser_demo')
    parser.add_argument('--output',type=Path,default=ROOT/'build/browser-tests/moss')
    parser.add_argument('--text',default='Прывітанне!')
    parser.add_argument('--max-frames',type=int,default=100)
    parser.add_argument('--no-stress',action='store_true')
    parser.add_argument('--raw-text',action='store_true',help='Diagnostic only: bypass Belarusian symbol/letter normalization for a supported-language control.')
    parser.add_argument('--trace',action='store_true',help='Record prompt and audio codes for native-reference comparison.')
    parser.add_argument('--chromium',default=shutil.which('chromium'))
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    server=ThreadingHTTPServer(('127.0.0.1',0),partial(RangeHandler,directory=str(args.demo.resolve())))
    threading.Thread(target=server.serve_forever,daemon=True).start()
    requests,errors=[],[]
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(executable_path=args.chromium,headless=True,args=['--disable-dev-shm-usage'])
            try:
                page=browser.new_page();base=f'http://127.0.0.1:{server.server_port}'
                if args.trace:
                    page.add_init_script('''(()=>{const NativeWorker=globalThis.Worker;
                      globalThis.Worker=class extends NativeWorker {
                        constructor(url,options){super(url,options);this.moss=String(url).endsWith('/moss-worker.js');}
                        postMessage(data,...rest){super.postMessage(this.moss && data.type==='synthesize'?{...data,diagnostics:true}:data,...rest);}
                      };})();''')
                page.on('request',lambda r:requests.append(r.url))
                page.on('pageerror',lambda e:errors.append(str(e)))
                page.on('crash',lambda:errors.append('Chromium renderer crashed'))
                page.on('response',lambda r:errors.append(f'HTTP {r.status}: {r.url}') if r.status>=400 else None)
                # Reject external traffic rather than merely observing it.
                page.route('**/*',lambda route:route.continue_() if route.request.url.startswith(base+'/') else route.abort())
                if args.raw_text:
                    page.route('**/data/normalization.json',lambda route:route.fulfill(json={}))
                page.goto(base+'/index.html')
                page.expose_function('mossEvent',lambda text:print('MOSS:',text,flush=True))
                page.evaluate('''async(options)=>{
                  const {createBelVoice}=await import('./belvoice.js');
                  const engine=createBelVoice({voice:'moss',onStatus:s=>window.mossEvent(s),onLog:s=>window.mossEvent(s)});
                  window.mossEngine=engine;
                  const started=performance.now();
                  engine.synthesize(options.text,{useStressML:options.stress,mossMaxFrames:options.frames}).then(result=>{
                    window.mossResult=result;window.mossElapsed=performance.now()-started;window.mossDone=true;
                  }).catch(error=>{window.mossError=String(error.stack ?? error);});
                }''',{'text':args.text,'stress':not args.no_stress,'frames':args.max_frames})
                page.wait_for_function('window.mossDone || window.mossError',timeout=1_200_000)
                error=page.evaluate('window.mossError');assert not error,error
                result=page.evaluate('''()=>{const r=window.mossResult;return {runtime:r.runtime,metrics:r.metrics,
                  normalized:r.normalized,stressML:r.stressML,warnings:r.warnings,elapsed:window.mossElapsed};}''')
                if args.trace:
                    (args.output/'trace.json').write_text(json.dumps(page.evaluate('window.mossResult.diagnostics')))
                with page.expect_download() as download:
                    page.evaluate('''()=>{const a=document.createElement('a');a.download='moss.wav';
                      a.href=URL.createObjectURL(new Blob([window.mossResult.wav],{type:'audio/wav'}));a.click();}''')
                download.value.save_as(args.output/'moss.wav')
                with wave.open(str(args.output/'moss.wav'),'rb') as wav:
                    pcm=np.frombuffer(wav.readframes(wav.getnframes()),dtype='<i2')
                    assert wav.getframerate()==48000 and wav.getnchannels()==1
                    assert len(pcm)>2400 and np.any(pcm)
                assert result['runtime']['voice']=='moss' and result['runtime']['backend']=='wasm'
                assert result['stressML']['enabled']==(not args.no_stress)
                assert 0<result['metrics']['frames']<=args.max_frames
                assert not any('encode.onnx' in u or '/g2p/' in u or '/models/vocoder.onnx' in u or '/omni/' in u for u in requests)
                assert all(u.startswith(base+'/') for u in requests),requests
                assert not errors,errors
                page.evaluate('window.mossEngine.dispose()')
                (args.output/'report.json').write_text(json.dumps({'result':result,'requests':requests,'errors':errors},ensure_ascii=False,indent=2))
                print('VERIFIED local MOSS browser WAV:',json.dumps(result,ensure_ascii=False),flush=True)
            finally:
                (args.output/'requests.json').write_text(json.dumps(requests,indent=2))
                (args.output/'errors.json').write_text(json.dumps(errors,indent=2))
                browser.close()
    finally:
        server.shutdown();server.server_close()


if __name__=='__main__':
    main()
