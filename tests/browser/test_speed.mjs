import assert from 'node:assert/strict';
import {test} from 'node:test';
import {expandDurations} from '../../browser_demo/frontend.js';

const config={noise_scale:0,length_scale:1,squeeze:2,mel_channels:1};
const mean=Float32Array.from([1,2,3,4]);
const logs=Float32Array.from([Math.log(11),Math.log(21),Math.log(31),Math.log(41)]);

test('speed 1 keeps the original duration expansion',()=>{
  const original=expandDurations(mean,logs,config);
  assert.deepEqual(expandDurations(mean,logs,config,1),original);
});

test('speed changes frame counts without changing token values',()=>{
  const normal=expandDurations(mean,logs,config,1);
  const fast=expandDurations(mean,logs,config,1.4);
  const slow=expandDurations(mean,logs,config,0.75);
  assert.ok(fast.frames<normal.frames && slow.frames>normal.frames);
  assert.deepEqual([...new Set(fast.z)],[1,2,3,4]);
  assert.equal(fast.frames%2,0);
});

test('invalid speeds are rejected',()=>{
  for(const speed of [0,0.49,2.01,NaN,Infinity,'1',null]) {
    assert.throws(()=>expandDurations(mean,logs,config,speed));
  }
});
