import assert from 'node:assert/strict';
import {test} from 'node:test';
import {applyUsualStress,applyStressDictionary,applyStressPipeline} from '../../browser_demo/stress-pipeline.js';

test('StressUsual explicitly accents a single о/ё and never overwrites manual accents',()=>{
  assert.equal(applyUsualStress('Малако, ёлка, до́м, ма́лако; водаправод, молоко!'),
    'Малако́, ё́лка, до́м, ма́лако; водаправод, молоко!');
  assert.equal(applyUsualStress('о О Ё ё'), 'о́ О́ Ё́ ё́');
});

test('dictionary lookup preserves manual stress, spelling and initial capitalization',()=>{
  assert.equal(applyStressDictionary('Прывітанне прывітанне прывіта́нне невядомае',
    {'прывітанне':'прывіта́нне'}), 'Прывіта́нне прывіта́нне прывіта́нне невядомае');
});

test('local pipeline precedence: manual, usual, unambiguous dictionary, statistics, then ML',async()=>{
  const calls=[];
  const result=await applyStressPipeline('Малако прывітанне каралі ма́ма блэбла',{
    dictionary:{малако:'ма́лако',прывітанне:'прывіта́нне'},
    statistics:{прывітанне:'пры́вітанне',каралі:'каралі́',мама:'мама́'},
    predictSegment:async word=>{calls.push(word);return {stressed:'блэбла́',confidence:.9};},
  });
  assert.equal(result.text,'Малако́ прывіта́нне каралі́ ма́ма блэбла́');
  assert.deepEqual(calls,['блэбла']);
  assert.deepEqual(result.stageCounts,{usual:1,dictionary:1,statistical:1,ml:1});
});

test('known words do not invoke ML; unresolved words with multiple о remain eligible',async()=>{
  const known=await applyStressPipeline('Малако прывітанне',{dictionary:{прывітанне:'прывіта́нне'},statistics:{},
    predictSegment:async()=>{throw new Error('ML must not run');}});
  assert.equal(known.text,'Малако́ прывіта́нне');
  const calls=[];
  const unknown=await applyStressPipeline('молоко',{dictionary:{},statistics:{},
    predictSegment:async word=>{calls.push(word);return {stressed:'молоко́',confidence:.8};}});
  assert.equal(unknown.text,'молоко́');assert.deepEqual(calls,['молоко']);
});
