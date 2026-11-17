"""Run with: uv run python -m unittest discover -s tests/synth -p test_local_tts.py.

BelG2P tests use the real JAR/JVM (first run needs a download), not mocks.
The TTS lifecycle test mocks only expensive checkpoint loading/inference.
"""

import contextlib
import io
import unittest
from unittest.mock import MagicMock, patch

from belvoice.synth.phonemization.PhonemizationBelG2P import PhonemizationBelG2P
from belvoice.synth.stress.StressStat import StressStat


class StressStatTests(unittest.TestCase):
    def test_only_stat_dictionary_is_opened(self):
        from importlib.resources import files

        resources = files('belvoice.synth.stress')
        directory = MagicMock()
        directory.joinpath.side_effect = resources.joinpath
        with patch('belvoice.synth.stress.StressStat.importlib.resources.files', return_value=directory):
            stress = StressStat()
        directory.joinpath.assert_called_once_with('stresses-stat.json')
        self.assertEqual(stress.apply_stresses('абраза'), 'абра́за')

    def test_case_manual_stress_and_unknown_words(self):
        stress = StressStat()
        self.assertEqual(
            stress.apply_stresses('Абраза, абразы. А́браза! невядомаслова'),
            'Абра́за, абразы́. А́браза! невядомаслова',
        )


class PhonemizationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.g2p = PhonemizationBelG2P()

    def test_reference_and_automatic_stress(self):
        self.assertEqual(self.g2p.convert("Ён адказаў"), "jˈɔn atkazˈau̯")

    def test_glowtts_notation_and_punctuation(self):
        self.assertEqual(
            self.g2p.convert("Прывітанне! Гэта праверка беларускага сінтэзу маўлення."),
            "prɨvʲitˈanʲːɛ! ɣˈɛta pravʲˈɛrka bʲɛɫarˈuskaɣa sʲˈintɛzu mau̯lʲˈɛnʲːa.",
        )

    def test_manual_stress(self):
        self.assertNotEqual(self.g2p.convert("му́ка"), self.g2p.convert("мука́"))

    def test_phonetic_contradiction_retries_without_new_sounds(self):
        from belvoice.synth.normalization.NormalizationSimple import NormalizationSimple
        from org.alex73.fanetyka.impl import Huk

        text = NormalizationSimple().normalize('Подъезд. Съешь ещё этих мягких булок.')
        before = Huk.SKIP_ERRORS
        with self.assertWarnsRegex(RuntimeWarning, 'набліжанае вымаўленне'):
            phonemes = self.g2p.convert(text)
        self.assertEqual(Huk.SKIP_ERRORS, before)
        self.assertTrue(phonemes)
        alphabet = set('Iabdfgijklmnprstuvxzɔɛɣɨɫɱʂʐʲˈː̯͡β!,.?: -‒–—…')
        self.assertLessEqual(set(phonemes), alphabet)
        self.assertEqual(self.g2p.convert('Ён адказаў'), 'jˈɔn atkazˈau̯')

    def test_stat_stress_reaches_belg2p(self):
        stressed = StressStat().apply_stresses('абраза')
        self.assertEqual(stressed, 'абра́за')
        self.assertIn('ˈa', self.g2p.convert(stressed))

    def test_entire_java_output_inventory(self):
        from org.alex73.fanetyka.impl.str import ToStringIPA2TTS

        # characters.characters from the unchanged GlowTTS checkpoint config.
        alphabet = set("Iabdfgijklmnprstuvxzɔɛɣɨɫɱʂʐʲˈː̯͡β")
        for entry in ToStringIPA2TTS.TTS_IPA_MAP.entrySet():
            output = str(entry.getValue()).translate(self.g2p._GLOWTTS_NOTATION)
            self.assertLessEqual(set(output), alphabet, str(entry.getKey()))

    def test_whitespace_quotes_and_empty(self):
        self.assertEqual(self.g2p.convert("«Ён»\n\tадказаў"), "jˈɔn atkazˈau̯")
        self.assertEqual(self.g2p.convert(""), "")

    def test_cross_word_sounds_are_not_merged(self):
        from java.util import ArrayList
        from org.alex73.fanetyka.impl import Fanetyka3
        from org.alex73.fanetyka.impl.str import ToStringIPA2TTS

        words = ArrayList()
        words.add("шмат")
        words.add("тэксту")
        converter = Fanetyka3(self.g2p._config)
        converter.calcFanetyka(words)
        expected = str(converter.toString(ToStringIPA2TTS())).translate(self.g2p._GLOWTTS_NOTATION)
        self.assertEqual(self.g2p.convert("шмат тэксту"), expected)
        self.assertIn("t t", expected)


class SynthesisTests(unittest.TestCase):
    def test_reuse_and_reject_unknown_tokens(self):
        from belvoice.synth.tts.TTSCoquiTTS import TTSCoquiTTS

        module = "belvoice.synth.tts.TTSCoquiTTS"
        synthesizer = MagicMock()
        synthesizer.tts_config.characters.characters = "jɔnˈ"
        synthesizer.tts_config.characters.punctuations = " ."
        with patch(module + ".snapshot_download", return_value="/models"), patch(
            module + ".Synthesizer", return_value=synthesizer
        ) as load:
            tts = TTSCoquiTTS()
            tts.tts("jˈɔn", "first.wav")
            tts.tts("jˈɔn", "second.wav")
            load.assert_called_once()
            self.assertEqual(synthesizer.tts.call_count, 2)
            with self.assertRaisesRegex(ValueError, "GlowTTS"):
                tts.tts("ɦ", "bad.wav")
            with self.assertRaises(ValueError):
                tts.tts("...", "bad.wav")
            self.assertEqual(synthesizer.tts.call_count, 2)

    def test_cli_validation(self):
        from speak import main

        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as error:
                main(["   "])
            self.assertEqual(error.exception.code, 2)

    def test_cli_passes_stat_stress_to_phonemizer(self):
        from speak import main

        with patch(
            'belvoice.synth.phonemization.PhonemizationBelG2P.PhonemizationBelG2P'
        ) as g2p, patch('belvoice.synth.tts.TTSCoquiTTS.TTSCoquiTTS') as tts:
            g2p.return_value.convert.return_value = 'abrˈaza'
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main(['абраза', '--output', 'unused.wav']), 0)
            g2p.return_value.convert.assert_called_once_with('абра́за')
            tts.return_value.tts.assert_called_once_with('abrˈaza', 'unused.wav')


if __name__ == "__main__":
    unittest.main()
