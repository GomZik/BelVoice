import assert from 'node:assert/strict';
import {test} from 'node:test';
import {integerWords, normalizeNumbers} from '../../browser_demo/number-words.js';

test('integer cardinal forms, thousands gender and teen endings',()=>{
  for(const [input,expected] of [
    ['4','чатыры'],['18','васямнаццаць'],['1000','адна тысяча'],['2000','дзве тысячы'],
    ['2026','дзве тысячы дваццаць шэсць'],['11000','адзінаццаць тысяч'],
    ['21000','дваццаць адна тысяча'],['22000','дваццаць дзве тысячы'],
    ['1000000','адзін мільён'],['2000000','два мільёны'],['5000000','пяць мільёнаў'],
    ['100000000000000001','сто квадрыльёнаў адзін'],
  ]) assert.equal(integerWords(input),expected,input);
});

test('large values never pass through floating-point integer conversion',()=>{
  assert.equal(integerWords('9007199254740993'),
    'дзевяць квадрыльёнаў сем трыльёнаў сто дзевяноста дзевяць мільярдаў дзвесце пяцьдзясят чатыры мільёны семсот сорак тысяч дзевяцьсот дзевяноста тры');
});

test('leading zeroes and beyond-supported-scale integers retain every digit',()=>{
  assert.equal(integerWords('00123'),'нуль нуль адзін два тры');
  assert.equal(integerWords('1000000000000000000'),'адзін '+Array(18).fill('нуль').join(' '));
  for(const invalid of ['', '-1', '1.5', '١٢', 123]) assert.throws(()=>integerWords(invalid));
});

test('grouping, signed numbers and hyphens are handled without context inference',()=>{
  const compact=text=>normalizeNumbers(text).replace(/\s+/gu,' ').trim();
  for(const space of [' ','\u00a0','\u202f']) assert.equal(compact('1'+space+'000'),'адна тысяча');
  assert.equal(compact('−42'),'мінус сорак два');
  assert.equal(compact('10-20'),'дзесяць - дваццаць');
  assert.equal(compact('1\n000'),'адзін нуль нуль нуль');
  assert.equal(compact('1 2 3'),'адзін два тры');
  assert.equal(compact('2 жанчыны'),'два жанчыны');
  assert.equal(compact('<3'),'< тры');
});
