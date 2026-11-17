import {stressWordPattern} from './frontend.js';

const vowels=new Set('аеёіоуыэюя');
const vowelCount=word=>Array.from(word.toLowerCase()).filter(c=>vowels.has(c)).length;

// Same encoding as StressML._predict_segment: fixed 48 chars, left padding,
// UNK=1, reverse-aligned positions, and a pointer restricted to vowels.
export function encodeStressSegment(segment, config) {
  const lower=Array.from(segment.toLowerCase());
  const clipped=lower.slice(-config.max_len), pad=config.max_len-clipped.length;
  const ids=new BigInt64Array(config.max_len);
  const padMask=new Uint8Array(config.max_len), vowelMask=new Uint8Array(config.max_len);
  padMask.fill(1,0,pad);
  clipped.forEach((c,i)=>{
    ids[pad+i]=BigInt(config.char2id[c] ?? config.unk_id);
    vowelMask[pad+i]=vowels.has(c)?1:0;
  });
  return {ids,padMask,vowelMask,pad,offset:lower.length-clipped.length};
}

export function decodeStressPrediction(segment, encoded, logits) {
  let best=-1;
  for(let i=0;i<logits.length;i++) {
    if(encoded.vowelMask[i] && (best<0 || logits[i]>logits[best])) best=i;
  }
  // An exceptionally long word can have no vowel inside its final 48 chars.
  // Don't add an accent to a consonant just because argmax returned index 0.
  if(best<0) return null;
  let sum=0;
  for(let i=0;i<logits.length;i++) if(encoded.vowelMask[i]) sum+=Math.exp(logits[i]-logits[best]);
  const index=best-encoded.pad+encoded.offset;
  const chars=Array.from(segment);
  return {index,confidence:1/sum,stressed:chars.slice(0,index+1).join('')+'\u0301'+chars.slice(index+1).join('')};
}

export async function applyStressML(text, {isKnownWord, predictSegment}) {
  let output='', end=0, skippedKnown=0;
  const applied=[];
  for(const match of text.matchAll(stressWordPattern)) {
    const word=match[0];
    output+=text.slice(end,match.index);
    end=match.index+word.length;
    if(word.includes('\u0301') || vowelCount(word)<=1 || /[оё]/iu.test(word)) {
      output+=word;
      continue;
    }
    if(isKnownWord(word)) {skippedKnown++;output+=word;continue;}
    const parts=word.split('-'), stressed=[], confidences=[];
    for(const part of parts) {
      if(!part || !vowelCount(part) || /[оё]/iu.test(part) || isKnownWord(part)) {
        stressed.push(part);
      } else if(vowelCount(part)===1) {
        const chars=Array.from(part), index=chars.findIndex(c=>vowels.has(c.toLowerCase()));
        stressed.push(chars.slice(0,index+1).join('')+'\u0301'+chars.slice(index+1).join(''));
        confidences.push(1);
      } else {
        const prediction=await predictSegment(part);
        stressed.push(prediction?.stressed ?? part);
        if(prediction) confidences.push(prediction.confidence);
      }
    }
    const result=stressed.join('-');
    output+=result;
    if(result!==word) applied.push({word,stressed:result,confidence:Math.min(...confidences)});
  }
  return {text:output+text.slice(end),applied,skippedKnown};
}
