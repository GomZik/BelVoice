import {normalizeNumbers} from './number-words.js';

// Same boundary handling and model notation as PhonemizationBelG2P.py.
const notation = {w:'v', 'ʋ':'β', 'ɦ':'ɣ', 'ɡ':'g', 'ʒ':'ʐ', 'ʃ':'ʂ', 'ɪ':'ɨ', 'ɐ':'a'};
export const stressWordPattern = /[ёйцукенгшўзхфывапролджэячсмітьбю\-\u02bc\u0301]+/giu;
const tokensPattern = /[ёйцукенгшўзхфывапролджэячсмітьбюґ|\-\u0301\u02bc'’´]+|\s+|[^\s]/giu;

// Same integers as Python, then one character pass without recursive replacements.
// The character mapping is exported from Python, not duplicated.
export function normalizeText(text, normalization) {
  return Array.from(normalizeNumbers(text), c => normalization[c] ?? c).join('');
}

export function prepareText(text, normalization, stresses) {
  const normalized = normalizeText(text, normalization);
  return normalized.replace(stressWordPattern, word => {
    if (word.includes('\u0301')) return word;
    const stressed = stresses[word] ?? stresses[word.toLowerCase()];
    if (!stressed) return word;
    return word[0] !== word[0].toLowerCase()
      ? stressed[0].toUpperCase() + stressed.slice(1) : stressed;
  });
}

export function phonemizeText(text, convertPhrase) {
  const result = [], words = [];
  const flush = () => {
    if (words.length) { result.push(convertPhrase(words.join(' '))); words.length = 0; }
  };
  for (const token of text.match(tokensPattern) ?? []) {
    if (/^\s+$/u.test(token)) continue;
    if (/^[ёйцукенгшўзхфывапролджэячсмітьбюґ|\-\u0301\u02bc'’´]/iu.test(token) && token !== '-') {
      words.push(token);
    } else {
      flush();
      result.push('!,.?: -‒–—…'.includes(token) ? token : ' ');
    }
  }
  flush();
  return Array.from(result.join(' '), c => notation[c] ?? c).join('')
    .replace(/\s+/gu, ' ').trim().replace(/\s+([!,.?:…])/gu, '$1');
}

export function tokenize(text, config) {
  const encoded = Array.from(text, c => {
    const id = config.char_to_id[c];
    if (id === undefined) throw new Error(`Невядомы для GlowTTS сімвал: ${c}`);
    return id;
  });
  let ids = encoded;
  if (config.add_blank) {
    ids = [config.blank_id];
    for (const id of encoded) ids.push(id, config.blank_id);
  }
  if (config.use_eos_bos) ids = [config.bos_id, ...ids, config.eos_id];
  return ids;
}

export function expandDurations(mean, logDuration, config, speed = 1) {
  // GlowTTS.inference, deterministic checkpoint (noise_scale == 0).
  if (config.noise_scale !== 0) throw new Error('Гэты дэма-экспарт патрабуе noise_scale=0');
  if (!Number.isFinite(speed) || speed < 0.5 || speed > 2) throw new Error('Speed must be between 0.5 and 2.');
  const durations = Array.from(logDuration, d => Math.max(1, Math.ceil((Math.exp(d)-1)*config.length_scale/speed)));
  const frames = Math.floor(durations.reduce((a,b) => a+b, 0)/config.squeeze)*config.squeeze;
  if (frames < config.squeeze) throw new Error('Недастаткова кадраў для GlowTTS');
  const z = new Float32Array(config.mel_channels * frames);
  for (let channel=0; channel<config.mel_channels; channel++) {
    let frame=0;
    for (let token=0; token<durations.length && frame<frames; token++) {
      const end = Math.min(frame+durations[token], frames);
      z.fill(mean[channel*durations.length+token], channel*frames+frame, channel*frames+end);
      frame=end;
    }
  }
  return {z, frames};
}

export function encodeWav(samples, sampleRate) {
  const bytes = new ArrayBuffer(44 + samples.length*2), v = new DataView(bytes);
  const str = (pos, text) => Array.from(text).forEach((c,i) => v.setUint8(pos+i,c.charCodeAt(0)));
  str(0,'RIFF'); v.setUint32(4,36+samples.length*2,true); str(8,'WAVE');
  str(12,'fmt '); v.setUint32(16,16,true); v.setUint16(20,1,true); v.setUint16(22,1,true);
  v.setUint32(24,sampleRate,true); v.setUint32(28,sampleRate*2,true); v.setUint16(32,2,true); v.setUint16(34,16,true);
  str(36,'data'); v.setUint32(40,samples.length*2,true);
  // Coqui save_wav normalizes PCM16 to peak level. Keep floating PCM for playback.
  let peak=0;
  for (const sample of samples) peak=Math.max(peak,Math.abs(sample));
  const scale=32767/Math.max(.01,peak);
  samples.forEach((sample,i) => v.setInt16(44+i*2, Math.max(-32768,Math.min(32767,Math.round(sample*scale))),true));
  return bytes;
}
