"""Local Belarusian text -> BelG2P -> GlowTTS/HiFi-GAN -> WAV."""

import argparse
from pathlib import Path
import sys


def main(argv=None):
    parser = argparse.ArgumentParser(description="Агучыць беларускі тэкст праз BelVoice (CPU).")
    parser.add_argument("text", nargs="+", help="Беларускі тэкст; можна пазначаць націскі знакам U+0301")
    parser.add_argument("--output", type=Path, default=Path("output.wav"), help="Шлях да WAV (output.wav)")
    args = parser.parse_args(argv)
    text = ' '.join(args.text).strip()
    if not text:
        parser.error("Патрэбны непусты тэкст")
    if not args.output.parent.is_dir():
        parser.error(f"Каталог не існуе: {args.output.parent}")
    if args.output.is_dir():
        parser.error(f"Шлях да WAV з'яўляецца каталогам: {args.output}")

    stage = "загрузка залежнасцей"
    try:
        from belvoice.synth.normalization.NormalizationSimple import NormalizationSimple
        from belvoice.synth.stress.StressStat import StressStat
        from belvoice.synth.phonemization.PhonemizationBelG2P import PhonemizationBelG2P
        from belvoice.synth.tts.TTSCoquiTTS import TTSCoquiTTS

        text = NormalizationSimple().normalize(text)
        stage = "расстаноўка націскаў StressStat"
        text = StressStat().apply_stresses(text)
        stage = "фанемізацыя BelG2P (патрэбныя Java/JVM і JAR)"
        phonemes = PhonemizationBelG2P().convert(text)
        if not any(c.isalpha() for c in phonemes):
            raise ValueError("Пасля нармалізацыі не засталося беларускіх слоў")
        print("Фанемы:", phonemes, flush=True)
        print("Заўвага: націскі бяруцца са StressStat і BelG2P/GrammarDB; статыстычны выбар амографаў і невядомыя словы могуць гучаць няправільна.", file=sys.stderr)
        stage = "сінтэз GlowTTS/HiFi-GAN і запіс WAV"
        TTSCoquiTTS().tts(phonemes, str(args.output))
    except Exception as exc:
        print(f"Памылка ({stage}): {exc}", file=sys.stderr)
        return 1
    print(f"Гатова: {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
