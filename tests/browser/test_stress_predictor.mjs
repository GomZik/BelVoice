import assert from 'node:assert/strict';
import {test} from 'node:test';
import {createStressPredictor} from '../../browser_demo/stress-predictor.js';

function fixture() {
  const tensors=[],calls={loads:0,runs:0,failLoad:false,failRun:false};
  class Tensor {
    constructor(){tensors.push(this);}
    dispose(){this.disposed=true;}
  }
  const ort={Tensor,InferenceSession:{create:async()=>{
    calls.loads++;
    if(calls.failLoad) throw new Error('load failed');
    return {run:async()=>{
      calls.runs++;
      if(calls.failRun) throw new Error('run failed');
      return {logits:Object.assign(new Tensor(),{data:Float32Array.from([0,0,1,3])})};
    }};
  }}};
  const predict=createStressPredictor({ort,
    readJson:async()=>({max_len:4,char2id:{м:2,а:3},unk_id:1}),
    readBytes:async()=>new Uint8Array(),status:()=>{},log:()=>{}});
  return {predict,calls,tensors};
}

test('shared StressML predictor loads once, caches predictions and releases all tensors',async()=>{
  const {predict,calls,tensors}=fixture();
  const result=await predict('мама');assert.equal(result.stressed,'мама́');
  assert.equal(await predict('мама'),result);
  assert.equal(calls.loads,1);assert.equal(calls.runs,1);
  assert.ok(tensors.every(t=>t.disposed));
  assert.equal(await predict('мммм'),null);assert.equal(calls.runs,1);
});

test('StressML initialization retries and failed inference releases feeds',async()=>{
  const {predict,calls,tensors}=fixture();
  calls.failLoad=true;await assert.rejects(predict('мама'),/load failed/);
  calls.failLoad=false;calls.failRun=true;await assert.rejects(predict('мама'),/run failed/);
  assert.ok(tensors.every(t=>t.disposed));
  calls.failRun=false;assert.equal((await predict('мама')).stressed,'мама́');
  assert.equal(calls.loads,2);assert.equal(calls.runs,2);
});
