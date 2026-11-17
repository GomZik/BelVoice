import * as ort from './vendor/ort.wasm.min.mjs';
import {prepareText, phonemizeText, tokenize, expandDurations, encodeWav} from './frontend.js';
import {resolveNumThreads} from './runtime-config.js';
import {applyStressML, encodeStressSegment, decodeStressPrediction} from './stress-ml.js';

ort.env.wasm.proxy = false; // Already running in a dedicated Worker.
ort.env.wasm.wasmPaths = new URL('./vendor/', import.meta.url).href;

const log = text => postMessage({type:'log', text});
const status = text => postMessage({type:'status', text});
let loaded;
let busy = false;
let stressModel;
const stressPredictions=new Map();

async function predictStressSegment(segment) {
  if(stressPredictions.has(segment)) return stressPredictions.get(segment);
  if(!stressModel) stressModel=(async()=>{
    const config=await readJson('./models/stress-ml-config.json');
    const bytes=await readBytes('./models/stress-ml.onnx');
    status('Ініцыялізацыя StressML…');
    const session=await ort.InferenceSession.create(bytes,{executionProviders:['wasm'],graphOptimizationLevel:'all'});
    log('StressML загружаная; наступныя запыты выкарыстоўваюць тую ж мадэль.');
    return {config,session};
  })().catch(error=>{stressModel=undefined;throw error;});
  const {config,session}=await stressModel;
  const encoded=encodeStressSegment(segment,config);
  if(!encoded.vowelMask.some(Boolean)) return null;
  const feeds={ids:new ort.Tensor('int64',encoded.ids,[1,config.max_len]),
    pad_mask:new ort.Tensor('bool',encoded.padMask,[1,config.max_len]),
    vowel_mask:new ort.Tensor('bool',encoded.vowelMask,[1,config.max_len])};
  let output,prediction;
  try {
    output=await session.run(feeds);
    prediction=decodeStressPrediction(segment,encoded,output.logits.data);
  } finally {
    for(const tensor of Object.values(feeds)) tensor.dispose();
    if(output) for(const tensor of Object.values(output)) tensor.dispose();
  }
  if(stressPredictions.size>=512) stressPredictions.delete(stressPredictions.keys().next().value);
  stressPredictions.set(segment,prediction);
  return prediction;
}

async function readBytes(path) {
  const start=performance.now();
  status(`Загрузка ${path}`);
  const response = await fetch(new URL(path, import.meta.url));
  if (!response.ok) throw new Error(`${path}: HTTP ${response.status}. Праверце, ці сабраныя ўсе файлы browser_demo.`);
  const length = Number(response.headers.get('Content-Length'));
  const reader = response.body.getReader();
  const chunks=[];
  let received=0, last=0;
  while (true) {
    const {done,value} = await reader.read();
    if (done) break;
    chunks.push(value); received+=value.length;
    if (performance.now()-last>400) {
      status(`${path}: ${(received/2**20).toFixed(1)}${length ? ' / '+(length/2**20).toFixed(1) : ''} MiB`);
      last=performance.now();
    }
  }
  const bytes=new Uint8Array(received);
  let offset=0;
  for (const chunk of chunks) {bytes.set(chunk,offset); offset+=chunk.length;}
  log(`${path}: ${(received/2**20).toFixed(1)} MiB, ${((performance.now()-start)/1000).toFixed(2)} с`);
  return bytes;
}

async function readJson(path, gzip=false) {
  const bytes=await readBytes(path);
  if (gzip) {
    const stream=new Blob([bytes]).stream().pipeThrough(new DecompressionStream('gzip'));
    return new Response(stream).json();
  }
  return JSON.parse(new TextDecoder().decode(bytes));
}

async function load(requestedThreads = 0, voice = 'default') {
  const started=performance.now();
  if(!['default','female-1'].includes(voice)) throw new Error('Unknown voice.');
  const modelPath=voice==='female-1'?'./models/female-1':'./models';
  log(`Голас: ${voice}`);
  const numThreads=resolveNumThreads(requestedThreads, {
    crossOriginIsolated:self.crossOriginIsolated,
    hasSharedArrayBuffer:typeof SharedArrayBuffer!=='undefined',
    hardwareConcurrency:navigator.hardwareConcurrency,
  });
  ort.env.wasm.numThreads=numThreads;
  log(`Worker: crossOriginIsolated=${self.crossOriginIsolated}; WASM numThreads=${numThreads} (requested=${requestedThreads}); ONNX Runtime 1.31.1`);
  const normalization=await readJson('./data/normalization.json');
  const stresses=await readJson('./data/stresses-stat.json');
  const config=await readJson(`${modelPath}/config.json`);
  globalThis.belg2pResources=await readJson('./g2p/resources.json');
  globalThis.belg2pGrammar=await readJson('./g2p/grammar.json.gz',true);
  const g2p=await import('./g2p/belg2p.mjs');
  log(`BelG2P: ${globalThis.belg2pGrammar.paradigms.length} парадыгм; StressStat: ${Object.keys(stresses).length} запісаў`);
  const sessions={};
  let modelInitMs=0;
  try {
    for (const name of ['encoder','decoder','vocoder']) {
      const bytes=await readBytes(`${modelPath}/${name}.onnx`);
      status(`Ініцыялізацыя ${name}…`);
      const beforeInit=performance.now();
      sessions[name]=await ort.InferenceSession.create(bytes, {executionProviders:['wasm'], graphOptimizationLevel:'all'});
      modelInitMs+=performance.now()-beforeInit;
      log(`${name}: уваход ${sessions[name].inputNames}; выхад ${sessions[name].outputNames}`);
    }
  } catch(error) {
    await Promise.allSettled(Object.values(sessions).map(session=>session.release()));
    throw error;
  }
  log(`Мадэлі і слоўнікі гатовыя за ${((performance.now()-started)/1000).toFixed(2)} с; паўторныя запыты не перазагружаюць іх.`);
  const info={requestedThreads,numThreads,crossOriginIsolated:self.crossOriginIsolated,
    hardwareConcurrency:navigator.hardwareConcurrency || 1, sampleRate:config.sample_rate,runtimeVersion:'1.31.1',
    loadMs:performance.now()-started,modelInitMs,voice};
  return {normalization, stresses, config, g2p, sessions, info};
}

self.onmessage = async ({data}) => {
  if (data.type!=='synthesize' && data.type!=='load') return;
  if (data.type==='synthesize' && busy) {
    postMessage({type:'error',id:data.id,code:'BUSY',text:'A synthesis is already in progress.'});
    return;
  }
  if (data.type==='synthesize') busy=true;
  try {
    if (!loaded) loaded=load(data.numThreads ?? 0,data.voice ?? 'default').catch(error => {loaded=undefined; throw error;});
    const {normalization, stresses, config, g2p, sessions, info}=await loaded;
    if(data.type==='load') {
      postMessage({type:'response',id:data.id,result:info});
      return;
    }
    if(typeof data.text!=='string' || !data.text.trim()) throw new Error('Expected nonempty text.');
    const started=performance.now();
    status('Нармалізацыя, націскі і BelG2P…');
    let normalized=prepareText(data.text.trim(),normalization,stresses);
    let stressML={enabled:!!data.useStressML,applied:[],skippedKnown:0};
    let stressMlMs=0;
    if(data.useStressML) {
      status('StressML: націскі ў невядомых словах…');
      const beforeML=performance.now();
      const stressed=await applyStressML(normalized,{isKnownWord:g2p.hasDictionaryWord,predictSegment:predictStressSegment});
      normalized=stressed.text;
      stressML={enabled:true,applied:stressed.applied,skippedKnown:stressed.skippedKnown};
      stressMlMs=performance.now()-beforeML;
      log(`StressML: дапоўнена слоў ${stressML.applied.length}; захавана са слоўніка ${stressML.skippedKnown}; ${stressMlMs.toFixed(1)} мс.`);
    }
    const warnings=[];
    const phonemes=phonemizeText(normalized,phrase=>{
      const result=g2p.phonemize(phrase);
      const warning=g2p.getLastWarning();
      if(warning) {warnings.push(warning);log(warning);}
      return result;
    });
    if (!/[a-zɔɛɣɨɫɱʂʐβ]/u.test(phonemes)) throw new Error('У тэксце не засталося фанем для агучвання.');
    postMessage({type:'frontend',normalized,phonemes,stressML});
    const ids=tokenize(phonemes,config);
    const frontendMs=performance.now()-started;
    status('GlowTTS: тэкставы энкодэр…');
    const beforeEncoder=performance.now();
    const tokens=new ort.Tensor('int64',BigInt64Array.from(ids,BigInt),[1,ids.length]);
    const lengths=new ort.Tensor('int64',BigInt64Array.from([ids.length],BigInt),[1]);
    let encoded, expanded;
    try {
      encoded=await sessions.encoder.run({tokens,lengths});
      expanded=expandDurations(encoded.mean.data,encoded.log_duration.data,config,data.speed ?? 1);
    } finally {
      tokens.dispose(); lengths.dispose();
      if(encoded) for(const tensor of Object.values(encoded)) tensor.dispose();
    }
    const {z, frames}=expanded;
    const encoderMs=performance.now()-beforeEncoder;
    status(`GlowTTS: дэкодэр (${frames} кадраў)…`);
    const beforeDecoder=performance.now();
    const zTensor=new ort.Tensor('float32',z,[1,config.mel_channels,frames]);
    let decoded;
    try { decoded=await sessions.decoder.run({z:zTensor}); }
    finally { zTensor.dispose(); }
    const decoderMs=performance.now()-beforeDecoder;
    status('HiFi-GAN: генерацыя гуку…');
    const beforeVocoder=performance.now();
    let output, samples;
    try {
      output=await sessions.vocoder.run({mel:decoded.mel});
      samples=Float32Array.from(output.audio.data);
    } finally {
      decoded.mel.dispose();
      if(output) for(const tensor of Object.values(output)) tensor.dispose();
    }
    const vocoderMs=performance.now()-beforeVocoder;
    if (!samples.length || samples.some(v=>!Number.isFinite(v))) throw new Error('Мадэль вярнула некарэктны аўдыясігнал.');
    const wav=encodeWav(samples,config.sample_rate);
    const metrics={speed:data.speed ?? 1, frontendMs, stressMlMs, encoderMs, decoderMs, vocoderMs, totalMs:performance.now()-started,
      duration:samples.length/config.sample_rate, tokens:ids.length, frames, sampleRate:config.sample_rate};
    log(JSON.stringify(metrics,null,2));
    const result={samples,sampleRate:config.sample_rate,wav,metrics,normalized,phonemes,warnings,stressML};
    postMessage({type:'response',id:data.id,result},[samples.buffer,wav]);
  } catch(error) {
    const message=error.stack ?? String(error);
    postMessage({type:'error',id:data.id,code:data.type==='load'?'LOAD_ERROR':'SYNTHESIS_ERROR',text:message});
  } finally {
    if(data.type==='synthesize') busy=false;
  }
};
