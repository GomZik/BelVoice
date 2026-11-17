// Copy alongside belvoice.gleam. Library assets are loaded from the passed URL,
// not from the Gleam compiler's output directory or node_modules.
const describe = error => `${error?.code ? error.code + ': ' : ''}${error?.message ?? String(error)}`;

export function create(assetsUrl, numThreads, onLog, onStatus, onCreated, onError) {
  create_with_voice(assetsUrl, 'default', numThreads, onLog, onStatus, onCreated, onError);
}

export function create_with_voice(assetsUrl, voice, numThreads, onLog, onStatus, onCreated, onError) {
  // The public FFI function returns undefined (Gleam Nil), never a Promise.
  void (async () => {
    let engine;
    try {
      const base = new URL(assetsUrl, globalThis.location.href);
      if (!base.pathname.endsWith('/')) base.pathname += '/';
      base.search = ''; base.hash = '';
      const {createBelVoice} = await import(/* @vite-ignore */ new URL('belvoice.js', base).href);
      engine = createBelVoice({assetsUrl: base, voice, numThreads, onLog, onStatus});
      await engine.load();
    } catch (error) {
      engine?.dispose();
      onError(describe(error));
      return;
    }
    onCreated(engine);
  })();
}

export function synthesize(engine, text, onAudio, onError) {
  engine.synthesize(text).then(onAudio, error => onError(describe(error)));
}
export function synthesize_with_stress_ml(engine, text, useML, onAudio, onError) {
  engine.synthesize(text, {useStressML: useML}).then(onAudio, error => onError(describe(error)));
}
export function synthesize_with_options(engine, text, useML, speed, onAudio, onError) {
  engine.synthesize(text, {useStressML: useML, speed}).then(onAudio, error => onError(describe(error)));
}
export function dispose(engine) { engine.dispose(); }
export function samples(audio) { return audio.samples; }
export function wav(audio) { return audio.wav; }
export function sample_rate(audio) { return audio.sampleRate; }
export function phonemes(audio) { return audio.phonemes; }
export function normalized(audio) { return audio.normalized; }
export function duration(audio) { return audio.metrics.duration; }
export function speed(audio) { return audio.metrics.speed; }
export function voice(engine) { return engine.info.voice; }
export function stress_ml_enabled(audio) { return audio.stressML.enabled; }
export function stress_ml_word_count(audio) { return audio.stressML.applied.length; }
export function stress_ml_time_ms(audio) { return audio.metrics.stressMlMs; }
export function num_threads(engine) { return engine.info.numThreads; }
export function wav_url(audio) { return URL.createObjectURL(new Blob([audio.wav], {type: 'audio/wav'})); }
export function revoke_url(url) { URL.revokeObjectURL(url); }
