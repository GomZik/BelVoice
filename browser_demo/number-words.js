// Context-free cardinal integers. Keep aligned with Python number_words.py;
// test_normalization.py compares both implementations over thousands of inputs.
const units=['нуль','адзін','два','тры','чатыры','пяць','шэсць','сем','восем','дзевяць'];
const teens=['дзесяць','адзінаццаць','дванаццаць','трынаццаць','чатырнаццаць',
  'пятнаццаць','шаснаццаць','сямнаццаць','васямнаццаць','дзевятнаццаць'];
const tens=['','','дваццаць','трыццаць','сорак','пяцьдзясят','шэсцьдзясят','семдзесят','восемдзесят','дзевяноста'];
const hundreds=['','сто','дзвесце','трыста','чатырыста','пяцьсот','шэсцьсот','семсот','восемсот','дзевяцьсот'];
const scales=[[],['тысяча','тысячы','тысяч'],['мільён','мільёны','мільёнаў'],
  ['мільярд','мільярды','мільярдаў'],['трыльён','трыльёны','трыльёнаў'],['квадрыльён','квадрыльёны','квадрыльёнаў']];
const numberPattern=/[-−]?(?:[0-9]{1,3}(?:[ \u00a0\u202f][0-9]{3}(?![0-9]))+|[0-9]+)/gu;

export function integerWords(digits) {
  if(typeof digits!=='string' || !digits.length || /[^0-9]/u.test(digits)) throw new Error('Expected ASCII digits');
  if(digits.length>18 || (digits.length>1 && digits[0]==='0')) return Array.from(digits,c=>units[Number(c)]).join(' ');
  if(digits==='0') return units[0];
  const chunks=[];
  while(digits.length) {
    // Parse only triples: never round a large integer through a JS Number.
    chunks.push(Number(digits.slice(-3))); digits=digits.slice(0,-3);
  }
  const words=[];
  for(let scale=chunks.length-1;scale>=0;scale--) {
    const value=chunks[scale];
    if(!value) continue;
    if(value>=100) words.push(hundreds[Math.floor(value/100)]);
    const remainder=value%100;
    if(remainder>=10 && remainder<20) words.push(teens[remainder-10]);
    else {
      if(remainder>=20) words.push(tens[Math.floor(remainder/10)]);
      const unit=remainder%10;
      if(unit) words.push(scale===1 && unit<=2 ? (unit===1?'адна':'дзве') : units[unit]);
    }
    if(scale) {
      const ending=remainder>=11 && remainder<=14?2:value%10===1?0:value%10>=2 && value%10<=4?1:2;
      words.push(scales[scale][ending]);
    }
  }
  return words.join(' ');
}

export function normalizeNumbers(text) {
  return text.replace(numberPattern,(token,index)=>{
    const sign=/^[-−]/u.test(token)?token[0]:'';
    const digits=token.slice(sign.length).replace(/[ \u00a0\u202f]/gu,'');
    const previous=Array.from(text.slice(Math.max(0,index-2),index)).at(-1) ?? '';
    const attached=/[\p{L}\p{N}_]/u.test(previous);
    const prefix=sign && attached?sign:sign?' мінус ':'';
    return prefix+' '+integerWords(digits)+' ';
  });
}
