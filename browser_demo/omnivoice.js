import {normalizeText,encodeWav} from './frontend.js';
import {resolveNumThreads} from './runtime-config.js';

// Browser-only adapter: keep BelVoice's PCM/WAV/lifecycle API, use the pinned
// VocoLoco worker for OmniVoice's BPE, diffusion loop and Higgs audio decoder.
export class OmniVoiceBrowser {
  constructor(options, ErrorType) {
    this.ErrorType=ErrorType;
    this.options={...options,numThreads:options.numThreads ?? 0,backend:options.backend ?? 'webgpu',allowModelDownload:options.allowModelDownload ?? false};
    if(!['wasm','webgpu'].includes(this.options.backend)) throw this.error('INVALID_OPTIONS','OmniVoice backend must be wasm or webgpu.');
    if(typeof this.options.allowModelDownload!=='boolean') throw this.error('INVALID_OPTIONS','allowModelDownload must be a boolean.');
    if(!Number.isInteger(this.options.numThreads) || this.options.numThreads<0) throw this.error('INVALID_OPTIONS','numThreads must be a nonnegative integer.');
    for(const name of ['onLog','onStatus','onFrontend']) {
      if(this.options[name]!==undefined && typeof this.options[name]!=='function') throw this.error('INVALID_OPTIONS',`${name} must be a function.`);
    }
    this.url=new URL(options.assetsUrl ?? './',options.assetsUrl===undefined?import.meta.url:globalThis.location?.href ?? import.meta.url);
    if(!this.url.pathname.endsWith('/')) this.url.pathname+='/';
    this.url.search=''; this.url.hash='';
    this._info=null;
    this.worker=null;
    this.loading=null;
    this.busy=false;
    this.disposed=false;
    this.abort=new AbortController();
    this.jobId=0;
  }
  get info(){return this._info;}
  error(code,message){return new this.ErrorType(code,message);}
  notify(name,value){try{this.options[name]?.(value);}catch(error){console.error(error);}}
  async json(path){
    const response=await fetch(new URL(path,this.url),{signal:this.abort.signal});
    if(!response.ok) throw this.error('LOAD_ERROR',`${path}: HTTP ${response.status}. Run tools/browser_demo/prepare_omnivoice.py first.`);
    return response.json();
  }
  load(){
    if(this.disposed) return Promise.reject(this.error('DISPOSED','This engine was disposed.'));
    if(!this.options.allowModelDownload) return Promise.reject(this.error('DOWNLOAD_CONSENT_REQUIRED','OmniVoice downloads about 1.3 GB (WebGPU) or 2.5 GB (WASM). Set allowModelDownload=true only after explicit consent. Model weights are non-commercial.'));
    if(this.loading) return this.loading;
    const token={};this.loadToken=token;
    this.loading=this.initialize(token).catch(error=>{
      if(this.loadToken===token) this.stop(error);
      throw error;
    });
    return this.loading;
  }
  async initialize(token){
    const started=performance.now();
    this.notify('onStatus','OmniVoice: беларускі prompt і нармалізацыя…');
    const [normalization,reference,source]=await Promise.all([this.json('data/normalization.json'),this.json('omni/reference.json'),this.json('omni/source.json')]);
    if(this.disposed || this.loadToken!==token) throw this.error('DISPOSED','This engine was disposed or restarted.');
    if(reference.numCodebooks!==8 || !Number.isInteger(reference.tokenCount) || reference.tokenCount<1 ||
       !reference.refText || reference.refTokens?.length!==8*reference.tokenCount ||
       !reference.refTokens.every(n=>Number.isInteger(n)&&n>=0&&n<1024)) throw this.error('LOAD_ERROR','Invalid prepared Belarusian voice prompt.');
    this.normalization=normalization; this.reference=reference;
    this.notify('onLog',`OmniVoice: ${this.options.backend}; fixed Belarusian reference ${reference.duration.toFixed(2)} s; no Whisper or voice encoder in the browser.`);
    this.notify('onLog',`OmniVoice weights: CC-BY-NC; audio codec: Boson Higgs Audio 2 Community License. VocoLoco ${source.vocolocoRevision}.`);
    const numThreads=resolveNumThreads(this.options.numThreads,{
      crossOriginIsolated:globalThis.crossOriginIsolated,
      hasSharedArrayBuffer:typeof SharedArrayBuffer!=='undefined',
      hardwareConcurrency:globalThis.navigator?.hardwareConcurrency,
    });
    const ready=new Promise((resolve,reject)=>{this.pendingLoad={resolve,reject};});
    try {
      this.worker=new Worker(new URL('omnivoice-worker.js',this.url),{type:'module',name:'belvoice-omnivoice'});
      const worker=this.worker;
      worker.onmessage=event=>{if(this.worker===worker)this.receive(event.data);};
      worker.onerror=event=>{if(this.worker===worker)this.stop(this.error('WORKER_ERROR',event.message || 'OmniVoice Worker failed.'));};
      worker.onmessageerror=()=>{if(this.worker===worker)this.stop(this.error('WORKER_ERROR','Invalid OmniVoice Worker message.'));};
      const base=new URL(this.options.modelBaseUrl ?? source.modelBaseUrl,globalThis.location?.href ?? this.url).href.replace(/\/$/u,'');
      this.worker.postMessage({type:'init',backend:this.options.backend,forceCPU:this.options.backend==='wasm',
        numThreads,modelBaseUrl:base,confirmDownload:false});
    } catch(error){this.pendingLoad=null;throw error;}
    const actual=await ready;
    if(this.disposed || this.loadToken!==token) throw this.error('DISPOSED','This engine was disposed or restarted.');
    const backend=actual.backend==='engine'?'webgpu':'wasm';
    if(backend!==this.options.backend) throw this.error('LOAD_ERROR','Unexpected OmniVoice backend; no implicit larger-model fallback is allowed.');
    this._info=Object.freeze({voice:'omnivoice',engine:'omnivoice',backend,requestedThreads:this.options.numThreads,
      numThreads:backend==='wasm'?numThreads:0,crossOriginIsolated:!!globalThis.crossOriginIsolated,
      hardwareConcurrency:globalThis.navigator?.hardwareConcurrency || 1,sampleRate:24000,
      runtimeVersion:backend==='wasm'?source.ortVersion:`VocoLoco ${source.vocolocoRevision}`,
      loadMs:performance.now()-started,modelInitMs:this.initStarted?performance.now()-this.initStarted:0});
    this.notify('onLog',`OmniVoice ready: ${(this._info.loadMs/1000).toFixed(2)} s, ${backend}.`);
    return this._info;
  }
  async synthesize(text, options={}){
    if(this.disposed) throw this.error('DISPOSED','This engine was disposed.');
    if(typeof text!=='string' || !text.trim()) throw this.error('INVALID_TEXT','Expected nonempty Belarusian text.');
    const speed=options.speed ?? 1, steps=options.omniSteps ?? 16;
    if(!Number.isFinite(speed) || speed<0.5 || speed>2) throw this.error('INVALID_OPTIONS','speed must be between 0.5 and 2.');
    if(![8,16,32].includes(steps)) throw this.error('INVALID_OPTIONS','omniSteps must be 8, 16 or 32.');
    const useStressML=options.useStressML ?? false;
    if(typeof useStressML!=='boolean') throw this.error('INVALID_OPTIONS','useStressML must be a boolean.');
    if(this.busy) throw this.error('BUSY','A synthesis is already in progress.');
    this.busy=true;
    try {
      await this.load();
      if(this.disposed) throw this.error('DISPOSED','This engine was disposed.');
      const started=performance.now();
      let normalized=normalizeText(text.trim(),this.normalization).replace(/\s+/gu,' ').trim();
      if(Array.from(normalized).length>160) throw this.error('INVALID_TEXT','For this experimental mode use at most 160 characters after normalization.');
      let stressML={enabled:false,applied:[],skippedKnown:0},stressMlMs=0;
      if(useStressML) {
        const prepared=await this.prepareStress(text.trim());
        normalized=prepared.normalized;stressML=prepared.stressML;stressMlMs=prepared.stressMlMs;
      }
      if(this.disposed) throw this.error('DISPOSED','This engine was disposed.');
      const frontendMs=performance.now()-started;
      this.notify('onFrontend',{normalized,phonemes:'',stressML});
      if(this.disposed) throw this.error('DISPOSED','This engine was disposed.');
      const pcm=await new Promise((resolve,reject)=>{
        const jobId=++this.jobId;
        this.pending={resolve,reject,jobId,stepMs:0,decodeStart:null,decodeMs:0};
        this.worker.postMessage({type:'synthesize',jobId,text:normalized,lang:'be',
          refText:this.reference.refText,refTokens:Int32Array.from(this.reference.refTokens),
          numStep:steps,speed,tempo:1,denoise:true,autoGender:false,seed:42});
      });
      const samples=Float32Array.from(pcm.samples);
      if(!samples.length || samples.some(n=>!Number.isFinite(n))) throw this.error('SYNTHESIS_ERROR','Invalid OmniVoice audio.');
      const wav=encodeWav(samples,24000);
      const metrics={speed,steps,frontendMs,stressMlMs,encoderMs:0,decoderMs:pcm.decodeMs,vocoderMs:0,
        diffusionMs:pcm.stepMs,totalMs:performance.now()-started,duration:samples.length/24000,
        sampleRate:24000,tokens:pcm.tokens ?? 0,frames:0};
      this.notify('onLog',JSON.stringify(metrics,null,2));
      return {samples,wav,sampleRate:24000,normalized,phonemes:'',stressML,metrics,runtime:this._info,
        warnings:['Experimental OmniVoice: no BelG2P; text accents are hints, not guaranteed pronunciation; model weights are CC-BY-NC.']};
    } finally {this.busy=false;}
  }
  prepareStress(text){
    return new Promise((resolve,reject)=>{
      const id=++this.jobId;
      this.pendingText={resolve,reject,id};
      try {
        if(!this.textWorker) {
          const worker=new Worker(new URL('omnivoice-text-worker.js',this.url),{type:'module',name:'belvoice-omnivoice-text'});
          this.textWorker=worker;
          const fail=message=>{
            if(this.textWorker!==worker) return;
            worker.terminate();this.textWorker=null;
            this.pendingText?.reject(this.error('SYNTHESIS_ERROR',message));this.pendingText=null;
          };
          worker.onerror=event=>fail(event.message || 'StressML Worker failed.');
          worker.onmessageerror=()=>fail('Invalid StressML Worker message.');
          worker.onmessage=({data})=>{
            if(this.textWorker!==worker) return;
            if(data.type==='status') this.notify('onStatus',data.text);
            else if(data.type==='log') this.notify('onLog',data.text);
            else if(this.pendingText?.id===data.id) {
              const pending=this.pendingText;this.pendingText=null;
              if(data.type==='prepared') pending.resolve(data);
              else pending.reject(this.error('SYNTHESIS_ERROR',data.message || 'StressML failed.'));
            }
          };
        }
        this.textWorker.postMessage({type:'prepare',id,text});
      } catch(error){this.pendingText=null;reject(error);}
    });
  }
  receive(data){
    if(this.disposed) return;
    if(data.type==='progress'){
      this.notify('onStatus',`OmniVoice: ${data.detail ?? data.stage}`);
      if(data.phase==='session-main' && !this.initStarted) this.initStarted=performance.now();
      if(this.pending){
        if(data.stage==='generating') this.pending.stepMs+=data.stepMs ?? 0;
        if(data.stage==='preparing') this.pending.tokens=Number(/Target: (\d+)/u.exec(data.detail)?.[1]) || 0;
        if(data.stage==='decoding') this.pending.decodeStart=performance.now();
        if(data.stage==='postprocessing' && this.pending.decodeStart) this.pending.decodeMs=performance.now()-this.pending.decodeStart;
      }
      if(data.stage!=='downloading') this.notify('onLog',`OmniVoice: ${data.detail ?? data.stage}`);
    } else if(data.type==='plan'){
      this.notify('onLog',`OmniVoice model files: ${data.totalBytes?`${(data.totalBytes/2**30).toFixed(2)} GiB`:'size pending'}; cached ${((data.cachedBytes ?? 0)/2**30).toFixed(2)} GiB.`);
    } else if(data.type==='ready'){
      this.pendingLoad?.resolve(data); this.pendingLoad=null;
    } else if(data.type==='audio' && this.pending?.jobId===data.jobId){
      const pending=this.pending;this.pending=null;
      pending.resolve({samples:data.pcm,stepMs:pending.stepMs,decodeMs:pending.decodeMs,tokens:pending.tokens});
    } else if(data.type==='error'){
      this.stop(this.error(this.pendingLoad?'LOAD_ERROR':'SYNTHESIS_ERROR',data.message || 'OmniVoice failed.'));
      this.loading=null;
    }
  }
  stop(error){
    this.textWorker?.terminate();this.textWorker=null;
    this.pendingText?.reject(error);this.pendingText=null;
    this.worker?.terminate(); this.worker=null;this._info=null;this.initStarted=null;
    this.loading=null;this.loadToken=null;
    this.pendingLoad?.reject(error);this.pendingLoad=null;
    this.pending?.reject(error);this.pending=null;
  }
  dispose(){
    if(this.disposed) return;
    this.disposed=true;this.abort.abort();
    this.stop(this.error('DISPOSED','This engine was disposed.'));
  }
}
