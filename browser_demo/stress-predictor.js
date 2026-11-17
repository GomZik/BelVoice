import {encodeStressSegment,decodeStressPrediction} from './stress-ml.js';

// One lazily loaded model and a bounded prediction cache per owning Worker.
export function createStressPredictor({ort,readJson,readBytes,status,log}) {
  let model;
  const predictions=new Map();
  return async segment=>{
    if(predictions.has(segment)) return predictions.get(segment);
    if(!model) model=(async()=>{
      const config=await readJson('./models/stress-ml-config.json');
      const bytes=await readBytes('./models/stress-ml.onnx');
      status('Ініцыялізацыя StressML…');
      const session=await ort.InferenceSession.create(bytes,{executionProviders:['wasm'],graphOptimizationLevel:'all'});
      log('StressML загружаная; наступныя запыты выкарыстоўваюць тую ж мадэль.');
      return {config,session};
    })().catch(error=>{model=undefined;throw error;});
    const {config,session}=await model;
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
    if(predictions.size>=512) predictions.delete(predictions.keys().next().value);
    predictions.set(segment,prediction);
    return prediction;
  };
}
