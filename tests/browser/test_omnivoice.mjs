import assert from 'node:assert/strict';
import {afterEach,beforeEach,test} from 'node:test';
import {createBelVoice} from '../../browser_demo/belvoice.js';

const original={fetch:globalThis.fetch,Worker:globalThis.Worker,location:globalThis.location};
const tick=()=>new Promise(resolve=>setImmediate(resolve));
let requests;
class FakeWorker {
  static instances=[];
  constructor(url){this.url=url;this.messages=[];FakeWorker.instances.push(this);}
  postMessage(data){this.messages.push(data);}
  terminate(){this.terminated=true;}
  emit(data){this.onmessage?.({data});}
}
beforeEach(()=>{
  FakeWorker.instances=[];requests=[];
  globalThis.Worker=FakeWorker;
  globalThis.location=new URL('https://example.test/demo/');
  globalThis.fetch=async url=>{
    requests.push(String(url));
    const data=String(url).endsWith('normalization.json')?{'@':' слімак '}:
      String(url).endsWith('reference.json')?{numCodebooks:8,tokenCount:1,duration:0.04,refText:'Так.',refTokens:Array(8).fill(1)}:
      {modelBaseUrl:'https://weights.test/pinned',vocolocoRevision:'revision',ortVersion:'1.30.0'};
    return {ok:true,json:async()=>data};
  };
});
afterEach(()=>Object.assign(globalThis,original));

test('OmniVoice never downloads or starts a Worker before explicit consent',async()=>{
  const engine=createBelVoice({voice:'omnivoice',backend:undefined,numThreads:undefined,allowModelDownload:undefined});
  await assert.rejects(engine.load(),{code:'DOWNLOAD_CONSENT_REQUIRED'});
  await assert.rejects(engine.synthesize('Так.'),{code:'DOWNLOAD_CONSENT_REQUIRED'});
  await assert.rejects(engine.synthesize('Так.',{useStressML:true}),{code:'DOWNLOAD_CONSENT_REQUIRED'});
  assert.equal(requests.length,0);assert.equal(FakeWorker.instances.length,0);
  engine.dispose();
});

test('OmniVoice validation and preload ownership',async()=>{
  assert.throws(()=>createBelVoice({voice:'omnivoice',backend:'auto'}),{code:'INVALID_OPTIONS'});
  const engine=createBelVoice({voice:'omnivoice',allowModelDownload:true,backend:'wasm',assetsUrl:'/voice/'});
  const first=engine.load();assert.equal(engine.load(),first);
  await tick();
  const worker=FakeWorker.instances[0];
  assert.equal(worker.url.href,'https://example.test/voice/omnivoice-worker.js');
  assert.equal(worker.messages[0].forceCPU,true);
  worker.emit({type:'ready',backend:'cpu'});
  assert.equal((await first).backend,'wasm');
  for(const options of [{useStressML:'yes'},{speed:0},{omniSteps:7}]) await assert.rejects(engine.synthesize('Так.',options),{code:'INVALID_OPTIONS'});
  engine.dispose();assert.ok(worker.terminated);
});

test('prepared voice tokens, text normalization, step metrics and owned PCM/WAV',async()=>{
  const engine=createBelVoice({voice:'omnivoice',allowModelDownload:true,backend:'wasm'});
  const pending=engine.synthesize('1000',{omniSteps:8,speed:1.35});
  await tick();
  const worker=FakeWorker.instances[0];worker.emit({type:'ready',backend:'cpu'});
  await tick();
  const msg=worker.messages[1];
  assert.equal(msg.text,'адна тысяча');assert.equal(msg.lang,'be');
  assert.equal(msg.refTokens.length,8);assert.equal(msg.autoGender,false);assert.equal(msg.refAudio,undefined);
  assert.equal(msg.numStep,8);assert.equal(msg.speed,1.35);
  assert.equal(FakeWorker.instances.length,1,'No StressML worker when disabled');
  await assert.rejects(engine.synthesize('Другі'),{code:'BUSY'});
  worker.emit({type:'progress',stage:'generating',step:1,numStep:8,stepMs:123});
  worker.emit({type:'audio',jobId:msg.jobId,pcm:Float32Array.from([0,0.1,-0.2]),sampleRate:24000});
  const result=await pending;
  assert.equal(result.sampleRate,24000);assert.equal(result.metrics.diffusionMs,123);
  assert.equal(result.metrics.steps,8);assert.equal(result.phonemes,'');
  assert.equal(new TextDecoder().decode(new Uint8Array(result.wav,0,4)),'RIFF');
  engine.dispose();assert.equal(result.samples.length,3);
});

test('load failure can be retried, but dispose cancels an active generation',async()=>{
  const engine=createBelVoice({voice:'omnivoice',allowModelDownload:true,backend:'wasm'});
  const first=engine.load();await tick();
  FakeWorker.instances[0].emit({type:'error',message:'Failed model'});
  await assert.rejects(first,{code:'LOAD_ERROR'});
  const second=engine.load();await tick();
  const worker=FakeWorker.instances[1];worker.emit({type:'ready',backend:'cpu'});
  await second;
  const synthesis=engine.synthesize('Так.');await tick();engine.dispose();
  await assert.rejects(synthesis,{code:'DISPOSED'});
  assert.equal(engine.info,null);
});

test('explicit WebGPU cannot silently become the larger WASM model',async()=>{
  const engine=createBelVoice({voice:'omnivoice',allowModelDownload:true});
  const loading=engine.load();await tick();
  const worker=FakeWorker.instances[0];assert.equal(worker.messages[0].backend,'webgpu');
  worker.emit({type:'ready',backend:'cpu'});
  await assert.rejects(loading,{code:'LOAD_ERROR'});
  assert.ok(worker.terminated);engine.dispose();
});

test('optional StressML sends accented text, reuses its worker and can be disabled per call',async()=>{
  const engine=createBelVoice({voice:'omnivoice',allowModelDownload:true,backend:'wasm',assetsUrl:'/voice/'});
  const loading=engine.load();await tick();
  const worker=FakeWorker.instances[0];worker.emit({type:'ready',backend:'cpu'});await loading;
  const pending=engine.synthesize('Крыптавалюта.',{useStressML:true});await tick();
  const textWorker=FakeWorker.instances[1];
  assert.equal(textWorker.url.href,'https://example.test/voice/omnivoice-text-worker.js');
  await assert.rejects(engine.synthesize('Так.'),{code:'BUSY'});
  const request=textWorker.messages[0];assert.equal(request.text,'Крыптавалюта.');
  assert.equal(worker.messages.length,1,'No diffusion before accents are ready');
  textWorker.emit({type:'prepared',id:request.id,normalized:'Крыптавалю́та.',stressMlMs:12,
    stressML:{enabled:true,applied:[{word:'Крыптавалюта',stressed:'Крыптавалю́та',confidence:0.8}],skippedKnown:0}});
  await tick();
  const msg=worker.messages.at(-1);assert.equal(msg.text,'Крыптавалю́та.');
  assert.equal(msg.lang,'be');assert.equal(msg.seed,42);assert.equal(msg.tempo,1);
  worker.emit({type:'audio',jobId:msg.jobId,pcm:Float32Array.from([0,0.1]),sampleRate:24000});
  const result=await pending;assert.equal(result.stressML.enabled,true);assert.equal(result.metrics.stressMlMs,12);
  assert.equal(result.normalized,msg.text);assert.equal(result.phonemes,'');
  const plain=engine.synthesize('Так.',{useStressML:false});await tick();
  assert.equal(textWorker.messages.length,1);
  worker.emit({type:'audio',jobId:worker.messages.at(-1).jobId,pcm:Float32Array.from([0,0.1]),sampleRate:24000});
  assert.equal((await plain).stressML.enabled,false);
  const again=engine.synthesize('Так.',{useStressML:true});await tick();
  assert.equal(FakeWorker.instances.length,2);assert.equal(textWorker.messages.length,2);
  engine.dispose();await assert.rejects(again,{code:'DISPOSED'});
  assert.ok(textWorker.terminated);assert.ok(worker.terminated);
  assert.equal(worker.messages.length,3,'Cancelled text preparation cannot start diffusion');
});

test('StressML errors reject synthesis without unloading OmniVoice; text worker crashes can retry',async()=>{
  const engine=createBelVoice({voice:'omnivoice',allowModelDownload:true,backend:'wasm'});
  const loading=engine.load();await tick();
  const worker=FakeWorker.instances[0];worker.emit({type:'ready',backend:'cpu'});await loading;
  const first=engine.synthesize('Так.',{useStressML:true});await tick();
  const textWorker=FakeWorker.instances[1];
  textWorker.emit({type:'error',id:textWorker.messages[0].id,message:'Failed StressML download'});
  await assert.rejects(first,/Failed StressML download/);assert.ok(engine.info);assert.equal(worker.terminated,undefined);
  const second=engine.synthesize('Так.',{useStressML:true});await tick();
  textWorker.onerror({message:'Crash'});await assert.rejects(second,/Crash/);assert.ok(textWorker.terminated);
  const third=engine.synthesize('Так.',{useStressML:true});await tick();
  assert.equal(FakeWorker.instances.length,3);engine.dispose();await assert.rejects(third,{code:'DISPOSED'});
});
