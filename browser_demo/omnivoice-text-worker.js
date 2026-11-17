// Text accents only: never load GlowTTS, its vocoder, or BelG2P. Keep this small
// WASM runtime isolated from VocoLoco's separately pinned GPU/CPU runtime.
import * as ort from './vendor/ort.wasm.min.mjs';
import {normalizeText} from './frontend.js';
import {applyStressPipeline} from './stress-pipeline.js';
import {createStressPredictor} from './stress-predictor.js';

ort.env.wasm.proxy=false;
ort.env.wasm.numThreads=1;
ort.env.wasm.wasmPaths=new URL('./vendor/',import.meta.url).href;
const status=text=>postMessage({type:'status',text});
const log=text=>postMessage({type:'log',text});
async function readBytes(path) {
  const response=await fetch(new URL(path,import.meta.url));
  if(!response.ok) throw new Error(`${path}: HTTP ${response.status}`);
  return new Uint8Array(await response.arrayBuffer());
}
async function readJson(path) {return JSON.parse(new TextDecoder().decode(await readBytes(path)));}
async function readDictionary() {
  status('Загрузка адназначных націскаў GrammarDB…');
  const bytes=await readBytes('./data/stresses-nohomographs.json.gz');
  const stream=new Blob([bytes]).stream().pipeThrough(new DecompressionStream('gzip'));
  return new Response(stream).json();
}
const predictSegment=createStressPredictor({ort,readJson,readBytes,status,log});
let resources,busy=false;
self.onmessage=async({data})=>{
  if(data.type!=='prepare') return;
  if(busy) {postMessage({type:'error',id:data.id,message:'Text preparation is busy.'});return;}
  busy=true;
  try {
    const started=performance.now();
    resources ??= Promise.all([readJson('./data/normalization.json'),readJson('./data/stresses-stat.json'),readDictionary()])
      .catch(error=>{resources=undefined;throw error;});
    const [normalization,statistics,dictionary]=await resources;
    const text=normalizeText(data.text,normalization).replace(/\s+/gu,' ').trim();
    status('StressML: націскі для OmniVoice…');
    const result=await applyStressPipeline(text,{dictionary,statistics,predictSegment});
    postMessage({type:'prepared',id:data.id,normalized:result.text,
      stressML:{enabled:true,applied:result.applied,skippedKnown:result.skippedKnown,stageCounts:result.stageCounts},
      stressMlMs:performance.now()-started});
  } catch(error) {
    postMessage({type:'error',id:data.id,message:String(error.stack ?? error)});
  } finally {busy=false;}
};
