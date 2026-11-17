"""Full NormalizationSimple parity, without loading JVM or neural models.

uv run python tools/browser_demo/test_normalization.py
Requires Node.js and browser_demo/data/normalization.json.
"""

import json
from pathlib import Path
import random
import subprocess
import unittest

from belvoice.synth.normalization.NormalizationSimple import NormalizationSimple
from belvoice.synth.normalization.number_words import integer_words

ROOT = Path(__file__).resolve().parents[2]


class NormalizationParityTests(unittest.TestCase):
    def test_cardinal_integer_words(self):
        expected = {
            '0': 'нуль', '4': 'чатыры', '10': 'дзесяць', '11': 'адзінаццаць',
            '12': 'дванаццаць', '14': 'чатырнаццаць', '16': 'шаснаццаць',
            '17': 'сямнаццаць', '18': 'васямнаццаць', '19': 'дзевятнаццаць',
            '20': 'дваццаць', '21': 'дваццаць адзін', '40': 'сорак', '50': 'пяцьдзясят',
            '60': 'шэсцьдзясят', '70': 'семдзесят', '80': 'восемдзесят', '90': 'дзевяноста',
            '100': 'сто', '125': 'сто дваццаць пяць', '200': 'дзвесце', '300': 'трыста',
            '400': 'чатырыста', '500': 'пяцьсот', '600': 'шэсцьсот', '700': 'семсот',
            '800': 'восемсот', '900': 'дзевяцьсот', '1000': 'адна тысяча',
            '1001': 'адна тысяча адзін', '2000': 'дзве тысячы', '2026': 'дзве тысячы дваццаць шэсць',
            '5000': 'пяць тысяч', '11000': 'адзінаццаць тысяч', '12000': 'дванаццаць тысяч',
            '14000': 'чатырнаццаць тысяч', '21000': 'дваццаць адна тысяча',
            '22000': 'дваццаць дзве тысячы', '25000': 'дваццаць пяць тысяч',
            '101000': 'сто адна тысяча', '111000': 'сто адзінаццаць тысяч',
            '1000000': 'адзін мільён', '2000000': 'два мільёны', '5000000': 'пяць мільёнаў',
            '11000000': 'адзінаццаць мільёнаў', '21000000': 'дваццаць адзін мільён',
            '1000000000': 'адзін мільярд', '2000000000': 'два мільярды',
            '1000000000000': 'адзін трыльён', '1000000000000000': 'адзін квадрыльён',
            '100000000000000001': 'сто квадрыльёнаў адзін',
            '1234567': 'адзін мільён дзвесце трыццаць чатыры тысячы пяцьсот шэсцьдзясят сем',
            '00123': 'нуль нуль адзін два тры', '00': 'нуль нуль',
            '1000000000000000000': 'адзін ' + ' '.join(['нуль'] * 18),
        }
        for number, words in expected.items():
            with self.subTest(number=number):
                self.assertEqual(integer_words(number), words)
                self.assertEqual(NormalizationSimple().normalize(number).strip(), words)
        for invalid in ['', '-1', '1.5', '١٢']:
            with self.assertRaises(ValueError):
                integer_words(invalid)

    def test_grouping_signs_and_no_context_guessing(self):
        expected = {
            '1 000': 'адна тысяча', '1\u00a0000': 'адна тысяча', '1\u202f000': 'адна тысяча',
            '12 345': 'дванаццаць тысяч трыста сорак пяць',
            '-42': 'мінус сорак два', '−42': 'мінус сорак два', '-1 000': 'мінус адна тысяча',
            '(-42)': '( мінус сорак два )', '10-20': 'дзесяць - дваццаць',
            '𝔄-12': '𝔄- дванаццаць', '00123': 'нуль нуль адзін два тры',
            '1 2 3': 'адзін два тры', '1234 567': 'адна тысяча дзвесце трыццаць чатыры пяцьсот шэсцьдзясят сем',
            '1 2345': 'адзін дзве тысячы трыста сорак пяць',
            '1\n000': 'адзін нуль нуль нуль', '1\t000': 'адзін нуль нуль нуль',
            '1.5': 'адзін . пяць', '1,5': 'адзін , пяць',
            '5 рублёў': 'пяць рублёў', '2 жанчыны': 'два жанчыны',
            '<3': 'менш тры', '@1000': 'слімак адна тысяча',
        }
        for text, words in expected.items():
            with self.subTest(text=text):
                self.assertEqual(' '.join(NormalizationSimple().normalize(text).split()), words)

    def test_special_symbols_and_punctuation(self):
        normalizer = NormalizationSimple()
        expected = {
            '@': 'слімак', '%': 'працэнт', '+': 'плюс', '=': 'роўна',
            '€': 'еўра', '$': 'долар', '#': 'рашотка', '&': 'амперсанд',
            '<': 'менш', '>': 'больш',
        }
        for symbol, name in expected.items():
            with self.subTest(symbol=symbol):
                self.assertEqual(normalizer.normalize(f'а{symbol}б'), f'а {name} б')
        punctuation = '!,.?: -‒–—… «»'
        self.assertEqual(normalizer.normalize(punctuation), punctuation)
        self.assertEqual(' '.join(normalizer.normalize('<3 >2').split()), 'менш тры больш два')

    def test_export_contains_every_python_rule(self):
        exported = json.loads((ROOT / 'browser_demo/data/normalization.json').read_text())
        self.assertEqual(exported, NormalizationSimple.C2NAME)

    def test_every_rule_and_mixed_text_match_python(self):
        samples = list(NormalizationSimple.C2NAME) + [
            '', ' ', '\n\t', ''.join(NormalizationSimple.C2NAME),
            'Прывітанне! 0123456789 ABC xyz Ии Щщ.',
            'Му́ка і мука́. Ўў Ёё Ґґ ʼ ’ \u0301',
            '@ # % + = / \\ & € $ <3 >2 🙂',
            '  user@example.com\n123 + 456 = 579!  ',
            '-42 −42 10-20 пункт-12 𝔄-12',
            '1 000 1\u00a0000 1\u202f000 1\n000 1\t000 00123',
            '1 2 3 1234 567 1 2345 1 000 2026',
            '1.5 1,5 12.03.2026 +1000 <3 >2',
            '9007199254740993 999999999999999999 1000000000000000000',
        ]
        samples += [str(number) for number in range(2000)]
        samples += [str(number * scale) for scale in [1000, 10**6, 10**9, 10**12, 10**15]
                    for number in [1, 2, 4, 5, 11, 12, 14, 21, 22, 24, 25, 101, 111, 121, 999]]
        rng = random.Random(42)
        for _ in range(500):
            number = str(rng.randrange(10**18))
            grouped = f'{int(number):,}'.replace(',', '\u202f')
            samples += [number, '-' + number, grouped]
        script = '''
import fs from 'node:fs';
import {normalizeText} from './browser_demo/frontend.js';
const rules=JSON.parse(fs.readFileSync('browser_demo/data/normalization.json'));
const samples=JSON.parse(fs.readFileSync(0,'utf8'));
console.log(JSON.stringify(samples.map(text=>normalizeText(text,rules))));
'''
        result = subprocess.run(['node', '--input-type=module', '-e', script], cwd=ROOT,
                                input=json.dumps(samples, ensure_ascii=False), text=True,
                                capture_output=True, check=True)
        actual = json.loads(result.stdout)
        normalizer = NormalizationSimple()
        self.assertEqual(actual, [normalizer.normalize(text) for text in samples])
        print(f'All {len(NormalizationSimple.C2NAME)} Python rules and {len(samples)} inputs match JavaScript exactly.')


if __name__ == '__main__':
    unittest.main()
