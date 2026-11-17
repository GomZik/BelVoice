"""Compare browser deterministic stress stages against original Python classes.

Needs the generated dictionary; no neural models are loaded.
"""
import gzip
import json
from pathlib import Path
import random
import subprocess

from belvoice.synth.stress.StressUsual import StressUsual
from belvoice.synth.stress.StressNoHomographs import StressNoHomographs
from belvoice.synth.stress.StressStat import StressStat

ROOT = Path(__file__).resolve().parents[2]


def main():
    dictionary = json.loads(gzip.decompress((ROOT / 'browser_demo/data/stresses-nohomographs.json.gz').read_bytes()))
    statistics = json.loads((ROOT / 'browser_demo/data/stresses-stat.json').read_text())
    words = random.Random(42).sample(list(dictionary), 2000)
    words += list(statistics)[:200]
    # Lowercase fixtures avoid the intentionally fixed initial-capitalization
    # loss in Python StressNoHomographs' lowercase fallback (tested separately).
    texts = [w.lower() for w in words]
    texts += ['малако ёлка мука абраза каралі', 'ма́лако прывіта́нне абра́за',
              '«прывітанне!»\nмалако, ёлка; 1000', 'абы-хто', 'водаправод молоко']
    used = {w: dictionary[w] for w in set(texts) if w in dictionary}
    # Include components of the multi-word fixtures without serializing 2M entries.
    used.update({w: dictionary[w] for w in ['прывітанне', 'малако', 'ёлка', 'мука', 'абраза', 'каралі', 'абы-хто', 'водаправод'] if w in dictionary})
    original = StressNoHomographs.__new__(StressNoHomographs)
    original._stresses_nohomographs = used
    stat = StressStat()
    expected = [stat.apply_stresses(original.apply_stresses(StressUsual().apply_stresses(text))) for text in texts]
    script = '''import fs from 'node:fs';
import {applyUsualStress,applyStressDictionary} from './browser_demo/stress-pipeline.js';
const {texts,dictionary,statistics}=JSON.parse(fs.readFileSync(0,'utf8'));
console.log(JSON.stringify(texts.map(text=>applyStressDictionary(applyStressDictionary(applyUsualStress(text),dictionary),statistics))));'''
    actual = json.loads(subprocess.check_output(['node', '--input-type=module', '-e', script], cwd=ROOT,
                        input=json.dumps({'texts':texts,'dictionary':used,'statistics':statistics}, ensure_ascii=False).encode()))
    for text, py, js in zip(texts, expected, actual):
        assert py == js, (text, py, js)
    print(f'VERIFIED original StressUsual → StressNoHomographs → StressStat parity: {len(texts)} cases, zero mismatches.')


if __name__ == '__main__':
    main()
