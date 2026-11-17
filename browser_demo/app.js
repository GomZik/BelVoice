import {createBelVoice} from './belvoice.js';

const $ = id => document.getElementById(id);
const button=$('speak'), status=$('status'), audio=$('audio');
let audioContext, playing, blobUrl;
let initialLoadMs;
let cancelled=false;
const isOmni=()=>$('voice').value==='omnivoice';
const isMoss=()=>$('voice').value==='moss';
const isTextEngine=()=>isOmni() || isMoss();
const seconds=ms=>`${(ms/1000).toFixed(2)} с`;
const log = text => {
  $('log').textContent+=`[${new Date().toLocaleTimeString()}] ${text}\n`;
  $('log').scrollTop=$('log').scrollHeight;
};
function finish() {
  button.disabled=false;$('use-stress-ml').disabled=false;$('voice').disabled=false;$('speed').disabled=false;
  $('omni-backend').disabled=false;$('omni-steps').disabled=false;$('omni-consent').disabled=false;$('cancel').hidden=true;
}
function fail(message) {
  status.textContent='Памылка — глядзіце дыягностыку'; status.classList.add('error');
  log(message); finish();
  window.demoError=message;
}
const makeEngine=()=>createBelVoice({
  voice:$('voice').value,
  backend:$('omni-backend').value,
  allowModelDownload:$('omni-consent').checked,
  ...(new URLSearchParams(location.search).has('omniModels') ? {modelBaseUrl:new URLSearchParams(location.search).get('omniModels')} : {}),
  numThreads:0,
  onLog:log,
  onStatus:text=>{status.textContent=text;},
  onFrontend:data=>{
    $('normalized').textContent=data.normalized; $('phonemes').textContent=isTextEngine()?`Не ўжываюцца: ${isMoss()?'SentencePiece MOSS':'тэкставы BPE-tokenizer OmniVoice'}.`:data.phonemes;
    const ml=data.stressML;
    $('ml-info').textContent=!ml?.enabled?'Выключана':ml.applied.length
      ? ml.applied.map(p=>`${p.word} → ${p.stressed} (${(p.confidence*100).toFixed(0)}%)`).join('; ')
      : 'Уключана; невядомых слоў для дапрацоўкі няма.';
    if(ml?.enabled && ml.stageCounts) {
      const c=ml.stageCounts;
      $('ml-info').textContent=`Правіла о/ё: ${c.usual}; GrammarDB: ${c.dictionary}; статыстыка: ${c.statistical}; ML: ${c.ml}. ${$('ml-info').textContent}`;
    }
  },
});
let tts=makeEngine();
$('speed').oninput=()=>{$('speed-value').textContent=`${Number($('speed').value).toFixed(2)}×`;};
const resetEngine=()=>{
  tts.dispose();
  audio.pause(); if(playing){playing.stop();playing=null;}
  if(blobUrl){URL.revokeObjectURL(blobUrl);blobUrl=null;}
  audio.removeAttribute('src');
  $('result').hidden=true;
  $('normalized').textContent='—'; $('phonemes').textContent='—';
  $('ml-info').textContent='—';
  initialLoadMs=undefined;
  window.demoLastResult=null; window.demoError=null;
  $('load-time').textContent='Яшчэ не запускалася'; $('wait-time').textContent='—';
  status.classList.remove('error'); status.textContent='Голас зменены — націсніце «Агучыць»';
  $('runtime').textContent='Рухавік папярэдняга голасу вызвалены.';
  log(`Выбраны голас: ${$('voice').selectedOptions[0].textContent}; папярэдні Worker спынены.`);
  tts=makeEngine();
  $('omni-options').hidden=!isOmni();
  $('moss-options').hidden=!isMoss();
  $('use-stress-ml').disabled=false;
};
$('voice').onchange=resetEngine;
$('omni-backend').onchange=()=>{$('omni-consent').checked=false;resetEngine();};
$('omni-consent').onchange=resetEngine;
$('cancel').onclick=()=>{
  cancelled=true;
  tts.dispose();
  status.textContent='Спынена; мадэлі рухавіка вызваленыя.';
  $('load-time').textContent='Запуск спынены';
  initialLoadMs=undefined;
  tts=makeEngine();
};

function renderResult(data, timing) {
    if(blobUrl) URL.revokeObjectURL(blobUrl);
    blobUrl=URL.createObjectURL(new Blob([data.wav],{type:'audio/wav'}));
    audio.src=blobUrl; $('download').href=blobUrl; $('result').hidden=false;
    const m=data.metrics;
    $('metrics').textContent=`Тэмп: ${m.speed.toFixed(2)}× · Гук: ${m.duration.toFixed(2)} с · Сінтэз: ${(m.totalMs/1000).toFixed(2)} с · ML: ${(m.stressMlMs ?? 0).toFixed(0)} мс · RTF: ${(m.totalMs/1000/m.duration).toFixed(2)} · ${m.sampleRate} Hz, mono`;
    $('stage-times').textContent=data.runtime.engine==='omnivoice'
      ? `Падрыхтоўка тэксту: ${seconds(m.frontendMs)} (у тым ліку ML: ${seconds(m.stressMlMs ?? 0)}) · Генерацыя: ${m.steps} крокаў, ${seconds(m.diffusionMs)} · Аўдыёкодэк: ${seconds(m.decoderMs)}`
      : data.runtime.engine==='moss'
      ? `Падрыхтоўка тэксту: ${seconds(m.frontendMs)} (націскі: ${seconds(m.stressMlMs)}) · Генерацыя: ${m.frames} кадраў, ${seconds(m.generationMs)} · Аўдыёкодэк: ${seconds(m.decoderMs)}`
      : `Падрыхтоўка тэксту: ${seconds(m.frontendMs)} (у тым ліку ML: ${seconds(m.stressMlMs ?? 0)}) · Энкодэр: ${seconds(m.encoderMs)} · Дэкодэр: ${seconds(m.decoderMs)} · Вакодэр: ${seconds(m.vocoderMs)}`;
    $('wait-time').textContent=`${seconds(timing.totalWaitMs)}; ${timing.coldStart?'першы запуск з загрузкай':'мадэлі ўжо былі ў памяці'}`;
    const buffer=audioContext.createBuffer(1,data.samples.length,data.sampleRate);
    buffer.copyToChannel(data.samples,0);
    playing=audioContext.createBufferSource(); playing.buffer=buffer;
    const source=playing;
    source.onended=()=>{
      if(playing===source){playing=null;status.textContent='Гатова';}
    };
    playing.connect(audioContext.destination); playing.start();
    window.demoLastResult={metrics:m,timing,wav:new Uint8Array(data.wav),runtime:data.runtime,warnings:data.warnings,stressML:data.stressML,normalized:data.normalized,phonemes:data.phonemes,audioContextState:audioContext.state};
    $('runtime').textContent=data.runtime.engine==='omnivoice'
      ? `OmniVoice · ${data.runtime.backend==='webgpu'?'WebGPU / FP16':`WASM / CPU, ${data.runtime.numThreads} патокі`}; crossOriginIsolated=${data.runtime.crossOriginIsolated}; ${m.sampleRate} Hz. Вагі: NC.`
      : `${data.runtime.engine==='moss'?'MOSS-TTS-Nano · Apache-2.0':`Голас: ${data.runtime.voice}`} · ONNX Runtime Web / WASM, ${data.runtime.numThreads} вылічальных патокаў, CPU; crossOriginIsolated=${data.runtime.crossOriginIsolated}; лагічных працэсараў: ${data.runtime.hardwareConcurrency}.`;
    if(data.runtime.engine==='moss') data.warnings.forEach(log);
    if(!data.runtime.crossOriginIsolated && data.runtime.backend!=='webgpu') log('Увага: няма cross-origin isolation; WASM працуе ў адным патоку. Праверце загалоўкі COOP/COEP на хостынгу.');
    status.textContent='Гатова — гук прайграваецца'; finish();
}
audio.onplay=()=>{if(playing){playing.stop();playing=null;}};
button.onclick=async()=>{
  const text=$('text').value.trim();
  if(!text){status.textContent='Увядзіце беларускі тэкст';return;}
  if(isTextEngine() && Array.from(text).length>160){status.textContent='Для гэтага рухавіка пакуль не больш за 160 сімвалаў; пачніце з кароткай фразы.';return;}
  if(isOmni() && !$('omni-consent').checked){status.textContent='Пацвердзіце загрузку і ліцэнзійнае абмежаванне OmniVoice.';return;}
  cancelled=false;
  const requestStarted=performance.now(), coldStart=!tts.info;
  let timer;
  button.disabled=true; $('use-stress-ml').disabled=true; $('voice').disabled=true; $('speed').disabled=true; status.classList.remove('error');
  $('omni-backend').disabled=true;$('omni-steps').disabled=true;$('omni-consent').disabled=true;$('cancel').hidden=false;
  window.demoError=null; window.demoLastResult=null;
  try {
    audio.pause(); if(playing){playing.stop();playing=null;}
    audioContext ??= new AudioContext();
    await audioContext.resume(); // Unlock on the user gesture, before long model loading.
    const loadStarted=performance.now();
    if(coldStart) {
      const update=()=>{$('load-time').textContent=`Загрузка і падрыхтоўка… ${seconds(performance.now()-loadStarted)}`;};
      update(); timer=setInterval(update,100);
    }
    const runtime=await tts.load();
    const loadWaitMs=performance.now()-loadStarted;
    clearInterval(timer);
    if(coldStart) {
      initialLoadMs=loadWaitMs;
      $('load-time').textContent=runtime.engine==='omnivoice'
        ? `${seconds(initialLoadMs)}; з іх ініцыялізацыя ${runtime.backend}: ${seconds(runtime.modelInitMs)}.`
        : `${seconds(initialLoadMs)}; з іх ініцыялізацыя ONNX/WASM: ${seconds(runtime.modelInitMs)}. Без асобнай загрузкі StressML.`;
      log(`Першая загрузка і падрыхтоўка (разам са стартам Worker): ${seconds(initialLoadMs)}; Worker: ${seconds(runtime.loadMs)}; ініцыялізацыя ONNX/WASM: ${seconds(runtime.modelInitMs)}.`);
    }
    const result=await tts.synthesize(text,{useStressML:$('use-stress-ml').checked,speed:Number($('speed').value),omniSteps:Number($('omni-steps').value)});
    const timing={coldStart,initialLoadMs,loadWaitMs,totalWaitMs:performance.now()-requestStarted};
    log(`Чаканне ад націскання да гатовага гуку: ${seconds(timing.totalWaitMs)}; сінтэз: ${seconds(result.metrics.totalMs)}.`);
    renderResult(result,timing);
  } catch(error) {
    if(cancelled){status.textContent='Спынена; можна запусціць нанова.';finish();return;}
    if(coldStart && !tts.info) $('load-time').textContent=`Загрузка не завершаная; ад націскання мінула ${seconds(performance.now()-requestStarted)}`;
    $('wait-time').textContent=`Памылка праз ${seconds(performance.now()-requestStarted)}`;
    fail(error.stack ?? String(error));
  } finally {clearInterval(timer);finish();}
};
log(`Браўзар: ${navigator.userAgent}`);
log(`Старонка: crossOriginIsolated=${crossOriginIsolated}; патокі будуць выбраныя паводле магчымасцяў асяроддзя.`);
window.addEventListener('pagehide',()=>tts.dispose());
