import assert from 'node:assert/strict';
import {test} from 'node:test';
import {buildMossRows,mossAudioToMono,seededMossRandom} from '../../browser_demo/moss-core.js';

test('MOSS prompt preserves text/reference boundary tokens and frame-major codebooks',()=>{
  const manifest={tts_config:{n_vq:16,audio_pad_token_id:1024,audio_start_token_id:6,
    audio_end_token_id:7,audio_user_slot_token_id:8},prompt_templates:{
    user_prompt_prefix_token_ids:[10],user_prompt_after_reference_token_ids:[11],assistant_prompt_prefix_token_ids:[12]}};
  const reference=[Array.from({length:16},(_,i)=>i)];
  const rows=buildMossRows(manifest,reference,[100,101]);
  assert.deepEqual(rows.map(r=>r[0]),[10,6,8,7,11,100,101,12,6]);
  assert.deepEqual(rows[2],[8,...reference[0]]);
  assert.ok(rows.filter((_,i)=>i!==2).every(r=>r.length===17 && r.slice(1).every(n=>n===1024)));
});

test('MOSS downmix respects output lengths and channel-major audio layout',()=>{
  const samples=mossAudioToMono({dims:[1,2,4],data:Float32Array.from([1,2,3,999,3,4,5,999])},3);
  assert.deepEqual([...samples],[2,3,4]);
  assert.throws(()=>mossAudioToMono({dims:[1,1,4],data:[]},3),/shape/);
  assert.throws(()=>mossAudioToMono({dims:[1,2,4],data:[]},5),/length/);
});

test('MOSS sampling uniforms are deterministic and remain within the graph domain',()=>{
  const a=seededMossRandom(),b=seededMossRandom();
  for(let i=0;i<1000;i++) {const x=a();assert.equal(x,b());assert.ok(x>=0 && x<1);}
});
