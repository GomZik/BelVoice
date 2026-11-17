"""Real browser test of the packaged library (no demo HTML) and Gleam FFI.

Requires dist/belvoice/ from package_library.py, Chromium, and gleam in PATH.
Tests both standard HTTP and cross-origin-isolated multithreaded WASM.
"""

import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, isolated=False, **kwargs):
        self.isolated = isolated
        super().__init__(*args, **kwargs)

    def end_headers(self):
        if self.isolated:
            self.send_header('Cross-Origin-Opener-Policy', 'same-origin')
            self.send_header('Cross-Origin-Embedder-Policy', 'require-corp')
        super().end_headers()

    def log_message(self, *_):
        pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package', type=Path, default=ROOT / 'dist/belvoice')
    parser.add_argument('--chromium', default=shutil.which('chromium'))
    parser.add_argument('--output', type=Path, default=ROOT / 'build/browser-tests/library')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    assert (args.package / 'belvoice.js').is_file(), 'Run package_library.py first'
    assert not (args.package / 'index.html').exists(), 'Library should not contain the demo UI'
    reports = []
    with tempfile.TemporaryDirectory(prefix='belvoice-host-') as temp:
        stage = Path(temp)
        (stage / 'public').mkdir()
        (stage / 'public/voice').symlink_to(args.package.resolve(), target_is_directory=True)
        bindings = stage / 'bindings'
        shutil.copytree(args.package / 'integrations/gleam', bindings)
        subprocess.run(['gleam', 'build', '--target', 'javascript'], cwd=bindings, check=True)
        (stage / 'gleam').symlink_to(bindings / 'build/dev/javascript', target_is_directory=True)
        (stage / 'host.html').write_text('<!doctype html><link rel="icon" href="data:,"><title>Host project</title>')
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=args.chromium, headless=True)
            try:
                for isolated in [False, True]:
                    server = ThreadingHTTPServer(('127.0.0.1', 0), partial(Handler, directory=str(stage), isolated=isolated))
                    threading.Thread(target=server.serve_forever, daemon=True).start()
                    page = browser.new_page()
                    requests, errors = [], []
                    page.on('request', lambda request: requests.append(request.url))
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    page.on('response', lambda response: errors.append(f'HTTP {response.status}: {response.url}') if response.status >= 400 else None)
                    base = f'http://127.0.0.1:{server.server_port}/'
                    try:
                        page.goto(base + 'host.html')
                        assert page.evaluate('crossOriginIsolated') == isolated
                        page.set_default_timeout(300_000)
                        report = page.evaluate('''async (isolated) => {
                          const {createBelVoice}=await import('/public/voice/belvoice.js');
                          const logs=[], frontend=[];
                          const voice=createBelVoice({assetsUrl:'/public/voice',numThreads:isolated?2:4,
                            onLog:message=>logs.push(message),onFrontend:data=>frontend.push(data)});
                          const a=voice.load(), b=voice.load();
                          if(a!==b) throw Error('Preload was not deduplicated');
                          const runtime=await a;
                          const summarize=audio=>{
                            if(!(audio.samples instanceof Float32Array) || !(audio.wav instanceof ArrayBuffer)) throw Error('Invalid buffer types');
                            if(new TextDecoder().decode(new Uint8Array(audio.wav,0,4))!=='RIFF') throw Error('Invalid WAV');
                            if(!audio.samples.some(value=>Math.abs(value)>.001)) throw Error('Silent PCM');
                            return {phonemes:audio.phonemes,normalized:audio.normalized,warnings:audio.warnings,
                              samples:audio.samples.length,metrics:audio.metrics};
                          };
                          const pending=voice.synthesize('Подъезд. Съешь ещё этих мягких булок.');
                          const busy=await voice.synthesize('Другі').then(()=>null,error=>error.code);
                          if(busy!=='BUSY') throw Error('Simultaneous synthesis was not rejected');
                          const first=await pending;
                          if(!first.warnings.length) throw Error('Missing phonetic warning');
                          const invalid=await voice.synthesize('ъ').then(()=>null,error=>error.code);
                          if(invalid!=='SYNTHESIS_ERROR') throw Error('Invalid input error lost');
                           const second=await voice.synthesize('стрымерскі 1000 <3',{useStressML:true});
                           if(!second.normalized.replaceAll('\u0301','').includes('адна тысяча')) throw Error('Integer normalization failed');
                          if(!second.stressML.enabled || second.stressML.applied.length!==1) throw Error('Optional StressML did not run');
                          const summary=[summarize(first),summarize(second)];
                          voice.dispose(); voice.dispose();
                          const disposed=await voice.synthesize('Пасля').then(()=>null,error=>error.code);
                          if(disposed!=='DISPOSED' || voice.info!==null) throw Error('Dispose lifecycle failed');
                          if(!second.samples.length) throw Error('Returned buffers were invalidated by dispose');
                          return {runtime,results:summary,logs,frontend,busy,invalid,disposed};
                        }''', isolated)
                        assert report['runtime']['numThreads'] == (2 if isolated else 1), report
                        for name in ['encoder.onnx', 'decoder.onnx', 'vocoder.onnx', 'stress-ml.onnx', 'grammar.json.gz']:
                            assert sum(url.endswith(name) for url in requests) == 1, f'Reloaded {name}'
                        if not isolated:
                            ffi = page.evaluate('''async () => {
                              const binding=await import('/gleam/belvoice_browser_ffi/belvoice.mjs');
                              const {Result$isOk,Result$Ok$0,Result$Error$0}=await import('/gleam/prelude.mjs');
                              const unwrap=result=>{
                                if(!Result$isOk(result)) throw Error(Result$Error$0(result));
                                return Result$Ok$0(result);
                              };
                              const engine=await new Promise((resolve,reject)=>{
                                const returned=binding.create('/public/voice/',0,()=>{},()=>{},result=>{
                                  try {resolve(unwrap(result));} catch(error) {reject(error);}
                                });
                                if(returned!==undefined) reject(Error('FFI returned a Promise instead of Nil'));
                              });
                              const audio=await new Promise((resolve,reject)=>{
                                const returned=binding.synthesize(engine,'Прывітанне!',result=>{
                                  try {resolve(unwrap(result));} catch(error) {reject(error);}
                                });
                                if(returned!==undefined) reject(Error('FFI returned a Promise instead of Nil'));
                              });
                              const url=binding.wav_url(audio);
                              const wav=await (await fetch(url)).arrayBuffer();
                              binding.revoke_url(url);
                              const result={sampleRate:binding.sample_rate(audio),numThreads:binding.num_threads(engine),
                                duration:binding.duration(audio),phonemes:binding.phonemes(audio),wavBytes:wav.byteLength,
                                pcmIsTyped:binding.samples(audio) instanceof Float32Array,
                                wavIsBuffer:binding.wav(audio) instanceof ArrayBuffer};
                              const mlAudio=await new Promise((resolve,reject)=>binding.synthesize_with_stress_ml(engine,'стрымерскі',true,value=>{
                                try {resolve(unwrap(value));} catch(error) {reject(error);}
                              }));
                              result.stressML={enabled:binding.stress_ml_enabled(mlAudio),words:binding.stress_ml_word_count(mlAudio),ms:binding.stress_ml_time_ms(mlAudio)};
                              if(!result.stressML.enabled || result.stressML.words!==1) throw Error('Gleam ML option failed');
                              binding.dispose(engine);
                              const failed=await new Promise(resolve=>binding.synthesize(engine,'Пасля',result=>resolve(!Result$isOk(result))));
                              if(!failed) throw Error('Gleam error callback failed');
                              const female=await new Promise((resolve,reject)=>{
                                const returned=binding.create_with_voice('/public/voice/','female-1',0,()=>{},()=>{},value=>{
                                  try {resolve(unwrap(value));} catch(error) {reject(error);}
                                });
                                if(returned!==undefined) reject(Error('create_with_voice returned a Promise'));
                              });
                              const synth=(speed)=>new Promise((resolve,reject)=>{
                                const returned=binding.synthesize_with_options(female,'Прывітанне, стрымерскі рудзі!',true,speed,value=>{
                                  try {resolve(unwrap(value));} catch(error) {reject(error);}
                                });
                                if(returned!==undefined) reject(Error('synthesize_with_options returned a Promise'));
                              });
                              const normal=await synth(1), fast=await synth(1.35);
                              result.female={voice:binding.voice(female),normalDuration:binding.duration(normal),fastDuration:binding.duration(fast),speed:binding.speed(fast)};
                              if(result.female.voice!=='female-1' || result.female.speed!==1.35 || result.female.fastDuration>=result.female.normalDuration) throw Error('Gleam female/speed controls failed');
                              if(!binding.stress_ml_enabled(fast) || !binding.wav(fast).byteLength) throw Error('Gleam female WAV/ML failed');
                              const invalidSpeed=await new Promise(resolve=>binding.synthesize_with_options(female,'Тэст',false,0,value=>resolve(!Result$isOk(value))));
                              if(!invalidSpeed) throw Error('Gleam speed validation failed');
                              binding.dispose(female);
                              return result;
                            }''')
                            assert ffi['sampleRate'] == 22050 and ffi['pcmIsTyped'] and ffi['wavIsBuffer'], ffi
                            report['gleam'] = ffi
                        assert not errors, errors
                        assert all(url.startswith(base) or url.startswith('blob:') for url in requests), requests
                        reports.append(report)
                        print('VERIFIED package and FFI:', json.dumps({
                            'runtime':report['runtime'], 'durations':[r['metrics']['duration'] for r in report['results']],
                            'synthesisMs':[r['metrics']['totalMs'] for r in report['results']], 'gleam':report.get('gleam'),
                        }, ensure_ascii=False), flush=True)
                    finally:
                        page.close()
                        server.shutdown()
                        server.server_close()
            finally:
                browser.close()
    (args.output / 'report.json').write_text(json.dumps(reports, ensure_ascii=False, indent=2))
    print('Verified relocation, no UI dependency, lifecycle, warnings, single synthesis, 1/2 WASM threads and real Gleam callbacks.')


if __name__ == '__main__':
    main()
