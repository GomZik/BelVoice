import assert from 'node:assert/strict';
import {test, beforeEach} from 'node:test';
import {createBelVoice, BelVoiceError} from '../../browser_demo/belvoice.js';
import {resolveNumThreads} from '../../browser_demo/runtime-config.js';

class FakeWorker {
  static instances=[];
  constructor(url, options) { this.url=url; this.options=options; this.messages=[]; FakeWorker.instances.push(this); }
  postMessage(message) {this.messages.push(message);}
  terminate() {this.terminated=true;}
  respond(message, result) {this.onmessage({data:{type:'response',id:message.id,result}});}
  error(message, code='SYNTHESIS_ERROR') {this.onmessage({data:{type:'error',id:message.id,code,text:'test error'}});}
}
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const info={numThreads:1,requestedThreads:0,sampleRate:22050,crossOriginIsolated:false};
beforeEach(()=>{FakeWorker.instances=[];globalThis.Worker=FakeWorker;});

test('loads once, resolves a subdirectory URL, shares preload and owns one Worker',async()=>{
  const engine=createBelVoice({assetsUrl:'https://example.test/public/voice'});
  assert.equal(FakeWorker.instances.length,0);
  const a=engine.load(), b=engine.load();
  assert.equal(a,b);
  const worker=FakeWorker.instances[0];
  assert.equal(worker.url.href,'https://example.test/public/voice/worker.js');
  assert.equal(worker.options.type,'module');
  assert.equal(worker.messages.length,1);
  worker.respond(worker.messages[0],info);
  assert.equal((await a).sampleRate,22050);
  assert.equal((await engine.load()).numThreads,1);
  assert.equal(worker.messages.length,1);
  engine.dispose();
  assert.ok(worker.terminated);
  assert.equal(engine.info,null);
});

test('synthesis is lazy, returns typed buffers and rejects simultaneous calls instead of queueing',async()=>{
  const engine=createBelVoice();
  const first=engine.synthesize('Прывітанне');
  await assert.rejects(engine.synthesize('Другі'),{code:'BUSY'});
  const worker=FakeWorker.instances[0];
  worker.respond(worker.messages[0],info);
  await tick();
  assert.equal(worker.messages[1].type,'synthesize');
  const samples=new Float32Array([.1,.2]), wav=new ArrayBuffer(48);
  worker.respond(worker.messages[1],{samples,wav,sampleRate:22050,warnings:[],phonemes:'test'});
  const result=await first;
  assert.equal(result.samples,samples);
  assert.equal(result.wav,wav);
  assert.equal(result.runtime,engine.info);
  const second=engine.synthesize('Яшчэ');
  await tick();
  assert.equal(worker.messages[2].type,'synthesize');
  worker.respond(worker.messages[2],{samples,wav});
  await second;
  assert.equal(FakeWorker.instances.length,1);
  engine.dispose();
});

test('dispose rejects active operations and is idempotent',async()=>{
  const engine=createBelVoice();
  const pending=engine.synthesize('test');
  engine.dispose(); engine.dispose();
  await assert.rejects(pending,{code:'DISPOSED'});
  await assert.rejects(engine.load(),{code:'DISPOSED'});
  await assert.rejects(engine.synthesize('next'),{code:'DISPOSED'});
});

test('a failed load can be retried in a clean Worker',async()=>{
  const engine=createBelVoice();
  const pending=engine.load();
  const old=FakeWorker.instances[0];
  old.error(old.messages[0],'LOAD_ERROR');
  await assert.rejects(pending,{code:'LOAD_ERROR'});
  assert.ok(old.terminated);
  const retry=engine.load();
  const fresh=FakeWorker.instances[1];
  fresh.respond(fresh.messages[0],info);
  await retry;
  engine.dispose();
});

test('a failed synthesis does not reload models or leave BUSY set',async()=>{
  const engine=createBelVoice();
  const first=engine.synthesize('bad');
  const worker=FakeWorker.instances[0];
  worker.respond(worker.messages[0],info);
  await tick();
  worker.error(worker.messages[1]);
  await assert.rejects(first,{code:'SYNTHESIS_ERROR'});
  const second=engine.synthesize('good');
  await tick();
  worker.respond(worker.messages[2],{samples:new Float32Array([1])});
  await second;
  assert.equal(worker.messages.filter(m=>m.type==='load').length,1);
  engine.dispose();
});

test('Worker crashes reject promises instead of hanging',async()=>{
  const engine=createBelVoice(), pending=engine.load();
  FakeWorker.instances[0].onerror({message:'failed import'});
  await assert.rejects(pending,{code:'WORKER_ERROR'});
  engine.dispose();
});

test('diagnostic callbacks do not interfere with request completion',async()=>{
  const frontend=[], statuses=[];
  const engine=createBelVoice({onLog:()=>{throw Error('consumer callback');},onFrontend:value=>frontend.push(value),onStatus:value=>statuses.push(value)});
  const pending=engine.load(), worker=FakeWorker.instances[0];
  const original=console.error;
  const reported=[];
  try {
    console.error=(...args)=>reported.push(args);
    worker.onmessage({data:{type:'log',text:'loading'}});
  } finally {console.error=original;}
  worker.onmessage({data:{type:'frontend',normalized:'тэкст',phonemes:'test'}});
  worker.onmessage({data:{type:'status',text:'ready'}});
  worker.respond(worker.messages[0],info);
  await pending;
  assert.equal(reported.length,1);
  assert.deepEqual(frontend,[{normalized:'тэкст',phonemes:'test'}]);
  assert.deepEqual(statuses,['ready']);
  engine.dispose();
});

test('dispose also cancels an already running synthesis',async()=>{
  const engine=createBelVoice(), pending=engine.synthesize('test');
  const worker=FakeWorker.instances[0];
  worker.respond(worker.messages[0],info);
  await tick();
  assert.equal(worker.messages[1].type,'synthesize');
  engine.dispose();
  await assert.rejects(pending,{code:'DISPOSED'});
  assert.ok(worker.terminated);
});

test('a queued ready response cannot resurrect a disposed instance',async()=>{
  const engine=createBelVoice(), pending=engine.load();
  const worker=FakeWorker.instances[0];
  worker.respond(worker.messages[0],info);
  engine.dispose();
  await assert.rejects(pending,{code:'DISPOSED'});
  assert.equal(engine.info,null);
});

test('invalid options/text fail before downloading models',async()=>{
  assert.throws(()=>createBelVoice({numThreads:-1}),BelVoiceError);
  assert.throws(()=>createBelVoice({numThreads:1.5}),BelVoiceError);
  assert.throws(()=>createBelVoice({onLog:42}),BelVoiceError);
  const engine=createBelVoice();
  await assert.rejects(engine.synthesize('  '),{code:'INVALID_TEXT'});
  await assert.rejects(engine.synthesize('test',{useStressML:'yes'}),{code:'INVALID_OPTIONS'});
  for(const speed of [0,0.49,2.01,NaN,Infinity,'1']) {
    await assert.rejects(engine.synthesize('test',{speed}),{code:'INVALID_OPTIONS'});
  }
  assert.equal(FakeWorker.instances.length,0);
  engine.dispose();
});

test('StressML is a per-call option, not a permanent mode or extra Worker',async()=>{
  const engine=createBelVoice(), first=engine.synthesize('test',{useStressML:true,speed:1.35});
  const worker=FakeWorker.instances[0];
  worker.respond(worker.messages[0],info); await tick();
  assert.equal(worker.messages[1].useStressML,true);
  assert.equal(worker.messages[1].speed,1.35);
  worker.respond(worker.messages[1],{}); await first;
  const second=engine.synthesize('test'); await tick();
  assert.equal(worker.messages[2].useStressML,false);
  assert.equal(worker.messages[2].speed,1);
  worker.respond(worker.messages[2],{}); await second;
  assert.equal(FakeWorker.instances.length,1);
  engine.dispose();
});

test('voice selection is validated and passed to a lazily created Worker',async()=>{
  assert.throws(()=>createBelVoice({voice:'unknown'}),{code:'INVALID_OPTIONS'});
  const engine=createBelVoice({voice:'female-1'});
  assert.equal(FakeWorker.instances.length,0);
  const loading=engine.load();
  const worker=FakeWorker.instances[0];
  assert.equal(worker.messages[0].voice,'female-1');
  worker.respond(worker.messages[0],{...info,voice:'female-1'});
  assert.equal((await loading).voice,'female-1');
  engine.dispose();
  assert.equal(worker.terminated,true);
});

test('thread selection is independent of the one-synthesis invariant',()=>{
  const available={crossOriginIsolated:true,hasSharedArrayBuffer:true,hardwareConcurrency:16};
  assert.equal(resolveNumThreads(0,available),4);
  assert.equal(resolveNumThreads(8,available),8);
  assert.equal(resolveNumThreads(1,available),1);
  assert.equal(resolveNumThreads(8,{...available,crossOriginIsolated:false}),1);
  assert.equal(resolveNumThreads(0,{...available,hasSharedArrayBuffer:false}),1);
});
