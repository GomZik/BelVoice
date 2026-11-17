// Thin launcher for the pinned, build-time-adapted VocoLoco worker.
// The vendor code and weights are never imported for the GlowTTS voices.
self.onmessage=async event=>{
  if(event.data.type!=='init') return;
  try {
    globalThis.belvoiceOmniThreads=event.data.numThreads;
    await import('./omni/vendor/vocoloco/workers/tts-worker.js');
    self.onmessage(event);
  } catch(error) {
    postMessage({type:'error',message:`OmniVoice Worker: ${error.stack ?? error}`});
  }
};
