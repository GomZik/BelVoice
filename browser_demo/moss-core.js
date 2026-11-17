// MOSS-TTS-Nano's public ONNX tensor/prompt contract. The Apache-2.0 Python
// reference is preserved with prepared assets; no Nano Reader code is used.
export function buildMossRows(manifest,reference,textIds) {
  const c=manifest.tts_config,p=manifest.prompt_templates;
  const textRow=id=>[id,...Array(c.n_vq).fill(c.audio_pad_token_id)];
  return [
    ...[...p.user_prompt_prefix_token_ids,c.audio_start_token_id].map(textRow),
    ...reference.map(codes=>[c.audio_user_slot_token_id,...codes]),
    ...[c.audio_end_token_id,...p.user_prompt_after_reference_token_ids,...textIds,
      ...p.assistant_prompt_prefix_token_ids,c.audio_start_token_id].map(textRow),
  ];
}

export function seededMossRandom(seed=42) {
  let state=seed>>>0;
  return ()=>{
    state=(Math.imul(state,1664525)+1013904223)>>>0;
    return Math.min(0.99999994,state/4294967296);
  };
}

export function mossAudioToMono(audio,length) {
  const [batch,channels,stride]=audio.dims;
  if(batch!==1 || channels!==2 || !Number.isInteger(length) || length<1 || length>stride) throw new Error('Invalid MOSS audio shape/length.');
  const result=new Float32Array(length),data=audio.data;
  for(let i=0;i<length;i++) result[i]=(data[i]+data[stride+i])*0.5;
  return result;
}
