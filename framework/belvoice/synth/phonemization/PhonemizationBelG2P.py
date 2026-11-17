import jpype
import jpype.imports
import os
import re
import warnings
import pooch

def start_jvm():
    if jpype.isJVMStarted():
        return

    jar_path = os.environ.get("PHONEMIZATION_BELG2P_JAR")
    if not jar_path:
        jar_path = pooch.retrieve(
            url="https://github.com/Belarus/BelG2P/releases/download/1.0.0/linguistics.BelG2P-1.0.0-jar-with-dependencies.jar",
            known_hash=None, # Можна дадаць хэш для праверкі цэласнасці
        )

    # Запускаем JVM
    jpype.startJVM(
        classpath=[jar_path],
        convertStrings=True
    )


class PhonemizationBelG2P:
    # BelG2P 1.0.0 out_ipa_tts.txt -> the older Huk.IPA alphabet used
    # by alex73/BelarusianTTSviaCoquiTTS (not ordinary modern IPA).
    # Reduced а has no separate token in that checkpoint: approximate it as а.
    _GLOWTTS_NOTATION = str.maketrans({
        'w': 'v', 'ʋ': 'β', 'ɦ': 'ɣ', 'ɡ': 'g',
        'ʒ': 'ʐ', 'ʃ': 'ʂ', 'ɪ': 'ɨ', 'ɐ': 'a',
    })

    def __init__(self):
        start_jvm()

        from org.alex73.fanetyka.impl import FanetykaConfig
        from org.alex73.grammardb import GrammarDB2
        from org.alex73.grammardb import GrammarFinder
        db = GrammarDB2.initializeFromJar()
        self.finder = GrammarFinder(db)
        self._config = FanetykaConfig(self.finder)

    def convert(self, text: str) -> str:
        """Return GlowTTS notation, with stress before the stressed vowel.

        Keep words together until punctuation to preserve cross-word phonetics.
        Fanetyka3 is single-use; the grammar database/config are reusable.
        """
        from org.alex73.fanetyka.impl import Fanetyka3, WordInitialConverter
        from org.alex73.fanetyka.impl.str import ToStringIPA2TTS
        from java.util import ArrayList

        letters = ("ёйцукенгшўзхфывапролджэячсмітьбюґ|-\u0301"
                   + str(WordInitialConverter.usie_apostrafy)
                   + str(WordInitialConverter.usie_naciski))
        tokens = re.findall(f"[{re.escape(letters)}]+|\\s+|.", text, re.IGNORECASE)
        words = ArrayList()
        result = []

        def flush():
            if not words.isEmpty():
                from java.lang import RuntimeException as JavaRuntimeException
                from org.alex73.fanetyka.impl import Huk

                def run():
                    converter = Fanetyka3(self._config)
                    converter.calcFanetyka(words)
                    return str(converter.toString(ToStringIPA2TTS()))

                try:
                    phonemes = run()
                except JavaRuntimeException as error:
                    message = str(error.getMessage())
                    # Only retry upstream's known, recoverable phonetic checks.
                    # Do not hide model/configuration errors or unrelated bugs.
                    if not message.startswith(('Небывае мяккі:', "У з'яве '")):
                        raise
                    previous = Huk.SKIP_ERRORS
                    try:
                        Huk.SKIP_ERRORS = True
                        phonemes = run()
                    finally:
                        Huk.SKIP_ERRORS = previous
                    warnings.warn(f"BelG2P: набліжанае вымаўленне ({message})", RuntimeWarning, stacklevel=2)
                result.append(phonemes)
                words.clear()

        for token in tokens:
            if token.isspace():
                continue
            if token[0].lower() in letters and token != '-':
                words.add(token)
            else:
                flush()
                # Quotes, brackets, emoji etc. are boundaries, not model tokens.
                result.append(token if token in '!,.?: -‒–—…' else ' ')
        flush()
        output = ' '.join(' '.join(result).translate(self._GLOWTTS_NOTATION).split())
        return re.sub(r'\s+([!,.?:…])', r'\1', output)
