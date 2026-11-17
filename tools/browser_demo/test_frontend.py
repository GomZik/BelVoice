"""Compare the compiled browser frontend with the real JVM/Python pipeline.

Includes examples from the BelG2P rule tables shipped in the downloaded JAR.
Requires Node.js, Java and the already built browser_demo artifacts.
"""

import json
from pathlib import Path
import subprocess

from belvoice.synth.normalization.NormalizationSimple import NormalizationSimple
from belvoice.synth.phonemization.PhonemizationBelG2P import PhonemizationBelG2P
from belvoice.synth.stress.StressStat import StressStat

ROOT = Path(__file__).resolve().parents[2]


def main():
    g2p, stress, normalization = PhonemizationBelG2P(), StressStat(), NormalizationSimple()
    samples = [
        'Прывітанне! Гэта праверка беларускага сінтэзу маўлення.',
        'Дзякуй за падтрымку! Ён адказаў.', 'му́ка і мука́', 'Абраза, абразы.',
        '«Ён»\nадказаў: 123 ABC.', 'Беларусь — мая краіна.',
        'шмат тэксту', 'без солі', 'не ў хаце', 'падпішыцеся на канал',
        'У Мінску сёння сонечна.', 'Дзень добры, сябры!', 'Жыццё працягваецца.',
        'З Новым годам!', 'Вольга, Мікола і Наталля.',
        '@ % + = € $ # & <3 >2',
        'Подъезд. Съешь ещё этих мягких булок.',
    ]
    for field in g2p._config.getClass().getDeclaredFields():
        if not str(field.getName()).startswith('process'):
            continue
        field.setAccessible(True)
        process = field.get(g2p._config)
        for example in process.getConfig().getExamples():
            word = str(example.word).replace('(', '').replace(')', '')
            samples.append(word)
    samples = list(dict.fromkeys(samples))
    fixtures, skipped = [], []
    for text in samples:
        try:
            prepared = stress.apply_stresses(normalization.normalize(text))
            fixtures.append({'text':text, 'normalized':prepared, 'phonemes':g2p.convert(prepared)})
        except Exception as error:
            skipped.append({'text':text, 'error':str(error)})
    assert len(fixtures) >= len(samples) * .95, 'Unexpected failure of JVM reference pipeline'
    script = '''
import fs from 'node:fs'; import zlib from 'node:zlib';
import {prepareText,phonemizeText,tokenize,expandDurations,encodeWav} from './browser_demo/frontend.js';
globalThis.belg2pGrammar=JSON.parse(zlib.gunzipSync(fs.readFileSync('browser_demo/g2p/grammar.json.gz')));
globalThis.belg2pResources=JSON.parse(fs.readFileSync('browser_demo/g2p/resources.json'));
const g2p=await import('./browser_demo/g2p/belg2p.mjs');
if(!g2p.hasDictionaryWord('прывітанне') || !g2p.hasDictionaryWord('беларускага')) throw Error('Dictionary guard lost known words');
if(g2p.hasDictionaryWord('стрымерскі') || g2p.hasDictionaryWord('неалагізмацыя')) throw Error('Dictionary guard lost OOV words');
const normalization=JSON.parse(fs.readFileSync('browser_demo/data/normalization.json'));
const stresses=JSON.parse(fs.readFileSync('browser_demo/data/stresses-stat.json'));
const fixtures=JSON.parse(fs.readFileSync(0,'utf8'));
const results=fixtures.map(f=>{
  try {
    const normalized=prepareText(f.text,normalization,stresses);
    return {normalized,phonemes:phonemizeText(normalized,g2p.phonemize)};
  } catch(error) {return {error:String(error)};}
});
// Best-effort mode must not leak to later phrases or swallow unrelated errors.
g2p.phonemize('ешь');
if(!g2p.getLastWarning()) throw Error('Missing best-effort warning');
g2p.phonemize('Ён адказаў');
if(g2p.getLastWarning()!==null) throw Error('Stale best-effort warning');
g2p.phonemize('ешь');
if(!g2p.getLastWarning()) throw Error('SKIP_ERRORS leaked to later calls');
let rejected=false;
try { g2p.phonemize('@'); } catch(error) { rejected=String(error).includes('Невядомая літара'); }
if(!rejected) throw Error('Unrelated error was swallowed');
const config=JSON.parse(fs.readFileSync('browser_demo/models/config.json'));
if(JSON.stringify(tokenize('jˈɔn',config))!==JSON.stringify([2,3,11,3,33,3,24,3,15,3,1])) throw Error('tokenizer mismatch');
const wav=encodeWav(new Float32Array([0,0.5,-0.5]),22050);
if(wav.byteLength!==50) throw Error('WAV size mismatch');
console.log(JSON.stringify(results));
'''
    run = subprocess.run(['node', '--input-type=module', '-e', script], cwd=ROOT,
                         input=json.dumps(fixtures, ensure_ascii=False), text=True, capture_output=True, check=True)
    results = json.loads(run.stdout)
    mismatches = []
    for expected, actual in zip(fixtures, results, strict=True):
        if actual.get('normalized') != expected['normalized'] or actual.get('phonemes') != expected['phonemes']:
            mismatches.append({'expected':expected, 'actual':actual})
    report = {'compared':len(fixtures), 'skipped_invalid_upstream_examples':skipped, 'mismatches':mismatches}
    (ROOT / 'browser_demo/g2p/verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(f'Compared {len(fixtures)} examples; skipped {len(skipped)} invalid upstream examples; mismatches {len(mismatches)}')
    if mismatches:
        print(json.dumps(mismatches, ensure_ascii=False, indent=2))
    assert not mismatches, f'{len(mismatches)} frontend mismatches'


if __name__ == '__main__':
    main()
