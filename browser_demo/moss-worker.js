import * as ort from './vendor/ort.wasm.min.mjs';
import {Tokenizer} from './moss/vendor/tokenizers.mjs';
import {timeStretch} from './moss/vendor/time-stretch.js';
import {normalizeText,encodeWav} from './frontend.js';
import {resolveNumThreads} from './runtime-config.js';
import {applyStressPipeline} from './stress-pipeline.js';
import {createStressPredictor} from './stress-predictor.js';
import {buildMossRows,seededMossRandom,mossAudioToMono} from './moss-core.js';

ort.env.wasm.proxy=false;
ort.env.wasm.wasmPaths=new URL('./vendor/',import.meta.url).href;
const status=text=>postMessage({type:'status',text});
const log=text=>postMessage({type:'log',text});
let loading,busy=false,stressResources;
async function readBytes(path,announce=true) {
  const url=new URL(path,import.meta.url);
  if(url.origin!==self.location.origin) throw new Error('MOSS assets must be local to this origin.');
  if(announce) status(`MOSS: загрузка ${path}`);
  const response=await fetch(url,{redirect:'error'});
  if(!response.ok) throw new Error(`${path}: HTTP ${response.status}. Run prepare_moss.py and package with --moss.`);
  return new Uint8Array(await response.arrayBuffer());
}
async function readJson(path) {return JSON.parse(new TextDecoder().decode(await readBytes(path)));}
const predictSegment=createStressPredictor({ort,readJson,readBytes,status,log});
async function stressData() {
  stressResources ??= (async()=>{
    const bytes=await readBytes('./data/stresses-nohomographs.json.gz');
    const stream=new Blob([bytes]).stream().pipeThrough(new DecompressionStream('gzip'));
    const dictionary=await new Response(stream).json();
    return {dictionary,statistics:await readJson('./data/stresses-stat.json')};
  })().catch(error=>{stressResources=undefined;throw error;});
  return stressResources;
}
function release(values) {for(const tensor of Object.values(values)) tensor.dispose();}
async function load(requestedThreads) {
  const started=performance.now();
  const numThreads=resolveNumThreads(requestedThreads,{crossOriginIsolated:self.crossOriginIsolated,
    hasSharedArrayBuffer:typeof SharedArrayBuffer!=='undefined',hardwareConcurrency:navigator.hardwareConcurrency});
  ort.env.wasm.numThreads=numThreads;
  const normalization=await readJson('./data/normalization.json');
  const manifest=await readJson('./moss/manifest.json');
  const weights=await readJson('./moss/weights.json');
  const reference=await readJson('./moss/reference.json');
  if(!reference.codes?.length || reference.codes.some(row=>row.length!==16 || row.some(n=>!Number.isInteger(n)||n<0||n>=1024))) throw new Error('Invalid fixed MOSS reference.');
  const tokenizer=new Tokenizer(await readJson('./moss/tokenizer.json'),{});
  const sessions={};let modelInitMs=0;
  try {
    // Share one fetched external-weight buffer between the two global graphs;
    // sessions are initialized sequentially, never concurrently with synthesis.
    for(const [folder,dataFile,graphs] of [
      ['tts','moss_tts_global_shared.data',[['prefill','moss_tts_prefill.onnx'],['decode','moss_tts_decode_step.onnx']]],
      ['tts','moss_tts_local_shared.data',[['frame','moss_tts_local_fixed_sampled_frame.onnx']]],
      ['codec','moss_audio_tokenizer_decode_shared.data',[['codec','moss_audio_tokenizer_decode_full.onnx']]],
    ]) {
      const weight=weights[`${folder}/${dataFile}`];
      if(!weight || !Number.isInteger(weight.bytes) || weight.bytes<1) throw new Error('Invalid local MOSS weights manifest.');
      const data=new Uint8Array(weight.bytes);let offset=0;
      status(`MOSS: загрузка ${dataFile} (${(weight.bytes/2**20).toFixed(1)} MiB)…`);
      for(const part of weight.parts) {
        const chunk=await readBytes(`./moss/${folder}/${part.path}`,false);
        if(chunk.length!==part.bytes || offset+chunk.length>data.length) throw new Error('Incomplete local MOSS weight shard.');
        data.set(chunk,offset);offset+=chunk.length;
      }
      if(offset!==data.length) throw new Error('Incomplete local MOSS weights.');
      for(const [key,file] of graphs) {
        const graph=await readBytes(`./moss/${folder}/${file}`);
        status(`MOSS: ініцыялізацыя ${key}…`);
        const before=performance.now();
        sessions[key]=await ort.InferenceSession.create(graph,{executionProviders:['wasm'],graphOptimizationLevel:'all',
          externalData:[{path:dataFile,data}]});
        modelInitMs+=performance.now()-before;
      }
    }
  } catch(error) {await Promise.allSettled(Object.values(sessions).map(session=>session.release()));throw error;}
  const info={voice:'moss',engine:'moss',backend:'wasm',requestedThreads,numThreads,
    crossOriginIsolated:!!self.crossOriginIsolated,hardwareConcurrency:navigator.hardwareConcurrency || 1,
    sampleRate:48000,runtimeVersion:'1.31.1',loadMs:performance.now()-started,modelInitMs};
  log(`MOSS ready: ${(info.loadMs/1000).toFixed(2)} s; ${numThreads} WASM threads; local Apache-2.0 weights; Belarusian is experimental.`);
  return {normalization,manifest,reference,tokenizer,sessions,info};
}

function takeState(outputs) {
  const tensor=outputs.global_hidden,width=tensor.dims.at(-1);
  const hidden=new Float32Array(tensor.data.slice(-width));
  tensor.dispose();delete outputs.global_hidden;
  return {hidden,past:Object.fromEntries(Object.entries(outputs).map(([name,value])=>[name.replace('present_','past_'),value]))};
}

async function generate(sessions,rows,maxFrames) {
  const c=16,random=seededMossRandom(),frames=[];
  const seen=new Int32Array(c*1024);
  const feeds={input_ids:new ort.Tensor('int32',Int32Array.from(rows.flat()),[1,rows.length,17]),
    attention_mask:new ort.Tensor('int32',new Int32Array(rows.length).fill(1),[1,rows.length])};
  let state;
  try {state=takeState(await sessions.prefill.run(feeds));} finally {release(feeds);}
  let ended=false;
  try {
    for(let step=0;step<maxFrames;step++) {
      const frameFeeds={global_hidden:new ort.Tensor('float32',state.hidden,[1,state.hidden.length]),
        repetition_seen_mask:new ort.Tensor('int32',seen,[1,c,1024]),
        assistant_random_u:new ort.Tensor('float32',Float32Array.of(random()),[1]),
        audio_random_u:new ort.Tensor('float32',Float32Array.from({length:c},random),[1,c])};
      let output,frame;
      try {
        output=await sessions.frame.run(frameFeeds);
        if(!Number(output.should_continue.data[0])) {ended=true;break;}
        frame=Int32Array.from(output.frame_token_ids.data);
      } finally {release(frameFeeds);if(output) release(output);}
      if(frame.length!==c || frame.some(n=>n<0||n>=1024)) throw new Error('Invalid MOSS frame.');
      frames.push(frame);
      for(let channel=0;channel<c;channel++) seen[channel*1024+frame[channel]]=1;
      if(step===0 || (step+1)%5===0) status(`MOSS: ${step+1} кадраў (${((step+1)/12.5).toFixed(2)} с гуку)…`);
      if(step+1===maxFrames) break;
      const next={input_ids:new ort.Tensor('int32',Int32Array.from([9,...frame]),[1,1,17]),
        past_valid_lengths:new ort.Tensor('int32',Int32Array.of(rows.length+step),[1])};
      let nextOutputs;
      try {nextOutputs=await sessions.decode.run({...next,...state.past});} finally {release(next);}
      release(state.past);state.past={};
      state=takeState(nextOutputs);
    }
  } finally {release(state.past);}
  if(!frames.length) throw new Error('MOSS generated no audio frames.');
  return {frames,ended};
}

async function synthesize(data,loaded) {
  const started=performance.now();
  const {normalization,manifest,reference,tokenizer,sessions}=loaded;
  let normalized=normalizeText(data.text.trim(),normalization).replace(/\s+/gu,' ').trim();
  if(Array.from(normalized).length>160) throw new Error('MOSS: at most 160 characters after normalization.');
  let stressML={enabled:false,applied:[],skippedKnown:0},stressMlMs=0;
  if(data.useStressML) {
    const before=performance.now();
    const result=await applyStressPipeline(normalized,{...await stressData(),predictSegment});
    normalized=result.text;
    stressML={enabled:true,applied:result.applied,skippedKnown:result.skippedKnown,stageCounts:result.stageCounts};
    stressMlMs=performance.now()-before;
  }
  postMessage({type:'frontend',normalized,phonemes:'',stressML});
  const textIds=tokenizer.encode(normalized,{add_special_tokens:false}).ids;
  const rows=buildMossRows(manifest,reference.codes,textIds);
  const frontendMs=performance.now()-started,beforeGenerate=performance.now();
  status('MOSS: генерацыя…');
  const {frames,ended}=await generate(sessions,rows,data.mossMaxFrames ?? 375);
  const generationMs=performance.now()-beforeGenerate,beforeDecode=performance.now();
  status('MOSS: дэкадаванне гуку…');
  const codes=new Int32Array(frames.length*16);frames.forEach((frame,i)=>codes.set(frame,i*16));
  const feeds={audio_codes:new ort.Tensor('int32',codes,[1,frames.length,16]),
    audio_code_lengths:new ort.Tensor('int32',Int32Array.of(frames.length),[1])};
  let output,samples;
  try {output=await sessions.codec.run(feeds);samples=mossAudioToMono(output.audio,Number(output.audio_lengths.data[0]));}
  finally {release(feeds);if(output) release(output);}
  const decoderMs=performance.now()-beforeDecode;
  // No native duration-conditioning knob in Nano's ONNX contract. Use explicit
  // pitch-preserving WSOLA, not AudioContext playbackRate, for this backend.
  samples=timeStretch(samples,48000,data.speed);
  if(samples.some(n=>!Number.isFinite(n))) throw new Error('Invalid MOSS waveform.');
  const wav=encodeWav(samples,48000),warnings=['Experimental Belarusian: not among MOSS-TTS-Nano\'s declared languages; native stereo is downmixed to mono.'];
  if(!ended) warnings.push('MOSS reached its frame limit; audio may be truncated.');
  const metrics={speed:data.speed,frontendMs,stressMlMs,encoderMs:0,decoderMs,vocoderMs:0,generationMs,
    totalMs:performance.now()-started,duration:samples.length/48000,sampleRate:48000,tokens:textIds.length,frames:frames.length};
  log(JSON.stringify(metrics,null,2));
  return {samples,wav,sampleRate:48000,normalized,phonemes:'',stressML,metrics,warnings,
    ...(data.diagnostics?{diagnostics:{textIds,rows,frames:frames.map(frame=>Array.from(frame))}}:{})};
}

self.onmessage=async({data})=>{
  if(!['load','synthesize'].includes(data.type)) return;
  if(data.type==='synthesize' && busy) {postMessage({type:'error',id:data.id,code:'BUSY',text:'MOSS is busy.'});return;}
  if(data.type==='synthesize') busy=true;
  try {
    loading ??= load(data.numThreads ?? 0).catch(error=>{loading=undefined;throw error;});
    const loaded=await loading;
    if(data.type==='load') {postMessage({type:'response',id:data.id,result:loaded.info});return;}
    const result=await synthesize(data,loaded);
    postMessage({type:'response',id:data.id,result},[result.samples.buffer,result.wav]);
  } catch(error) {
    postMessage({type:'error',id:data.id,code:data.type==='load'?'LOAD_ERROR':'SYNTHESIS_ERROR',text:String(error.stack ?? error)});
  } finally {if(data.type==='synthesize') busy=false;}
};
