import {stressWordPattern} from './frontend.js';
import {applyStressML} from './stress-ml.js';

// StressUsual: only a single о/ё gives an unambiguous stress. Never replace a
// user's accent, even when it disagrees with this rule or a dictionary.
export function applyUsualStress(text) {
  return text.replace(stressWordPattern,word=>{
    if(word.includes('\u0301')) return word;
    const positions=Array.from(word.matchAll(/[оё]/giu),match=>match.index);
    if(positions.length!==1) return word;
    const at=positions[0]+1;
    return word.slice(0,at)+'\u0301'+word.slice(at);
  });
}

// Same full-word lookup as StressNoHomographs/StressStat; preserve initial
// capitalization using BelVoice's word_match_case convention.
export function applyStressDictionary(text,dictionary) {
  return text.replace(stressWordPattern,word=>{
    if(word.includes('\u0301')) return word;
    const stressed=dictionary[word] ?? dictionary[word.toLowerCase()];
    if(!stressed) return word;
    return word[0]!==word[0].toLowerCase() && stressed[0]===stressed[0].toLowerCase()
      ? stressed[0].toUpperCase()+stressed.slice(1) : stressed;
  });
}

export async function applyStressPipeline(text,{dictionary,statistics,predictSegment}) {
  const stageCounts={usual:0,dictionary:0,statistical:0,ml:0};
  const stage=(name,apply)=>{
    const before=(text.match(/\u0301/gu) ?? []).length;
    text=apply(text);
    stageCounts[name]=(text.match(/\u0301/gu) ?? []).length-before;
  };
  stage('usual',applyUsualStress);
  stage('dictionary',value=>applyStressDictionary(value,dictionary));
  stage('statistical',value=>applyStressDictionary(value,statistics));
  // Unlike the phoneme path, merely seeing о/ё is not a substitute for sending
  // an explicit accent to OmniVoice. The single-vowel rule already ran above;
  // unresolved multi-о/ё words are eligible for the original ML fallback.
  const result=await applyStressML(text,{isKnownWord:()=>false,predictSegment,skipImplicitStress:false});
  stageCounts.ml=(result.text.match(/\u0301/gu) ?? []).length-(text.match(/\u0301/gu) ?? []).length;
  return {...result,stageCounts};
}
