import assert from 'node:assert/strict';
import {test} from 'node:test';
import {encodeStressSegment, decodeStressPrediction, applyStressML} from '../../browser_demo/stress-ml.js';

const config={max_len:6,unk_id:1,char2id:{'а':2,'б':3,'э':4}};

test('StressML encoding uses the original left padding and unknown IDs',()=>{
  const encoded=encodeStressSegment('Абэ',config);
  assert.deepEqual(Array.from(encoded.ids),[0n,0n,0n,2n,3n,4n]);
  assert.deepEqual(Array.from(encoded.padMask),[1,1,1,0,0,0]);
  assert.deepEqual(Array.from(encoded.vowelMask),[0,0,0,1,0,1]);
  assert.equal(encoded.offset,0);
  assert.deepEqual(Array.from(encodeStressSegment('я',config).ids),[0n,0n,0n,0n,0n,1n]);
});

test('pointer selects only vowels and preserves original case',()=>{
  const encoded=encodeStressSegment('Абэ',config);
  const prediction=decodeStressPrediction('Абэ',encoded,[-10000,-10000,-10000,1,999,2]);
  assert.equal(prediction.stressed,'Абэ́');
  assert.equal(prediction.index,2);
  assert.ok(Math.abs(prediction.confidence-1/(1+Math.exp(-1)))<1e-6);
});

test('long words keep original offsets and reject a tail without vowels',()=>{
  const encoded=encodeStressSegment('бабабабэ',config);
  assert.equal(encoded.offset,2);
  assert.equal(decodeStressPrediction('бабабабэ',encoded,[0,0,0,0,0,3]).stressed,'бабабабэ́');
  assert.equal(decodeStressPrediction('абббббббб',encodeStressSegment('абббббббб',config),[1,1,1,1,1,1]),null);
});

test('manual, statistical/dictionary stresses, о/ё and monosyllables are protected',async()=>{
  const calls=[];
  const result=await applyStressML('прывітанне му́ка блэбла дом ёлка кіт',{
    isKnownWord:word=>word==='прывітанне',
    predictSegment:async word=>{calls.push(word);return {stressed:'блэбла́',confidence:.9};},
  });
  assert.equal(result.text,'прывітанне му́ка блэбла́ дом ёлка кіт');
  assert.equal(result.skippedKnown,1);
  assert.deepEqual(calls,['блэбла']);
  assert.deepEqual(result.applied,[{word:'блэбла',stressed:'блэбла́',confidence:.9}]);
});

test('hyphenated OOV words preserve known segments',async()=>{
  const result=await applyStressML('кіт-блэбла!',{
    isKnownWord:word=>word==='кіт',predictSegment:async()=>({stressed:'блэбла́',confidence:.8}),
  });
  assert.equal(result.text,'кіт-блэбла́!');
  assert.equal(result.applied[0].confidence,.8);
});

test('a segment without an admissible prediction is left unchanged',async()=>{
  const result=await applyStressML('блэбла', {isKnownWord:()=>false,predictSegment:async()=>null});
  assert.equal(result.text,'блэбла');
  assert.deepEqual(result.applied,[]);
});
