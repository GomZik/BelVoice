from pathlib import Path

from huggingface_hub import snapshot_download
from TTS.utils.synthesizer import Synthesizer


class TTSCoquiTTS:
    MODEL_REPO = 'alex73/BelarusianTTSviaCoquiTTS'
    MODEL_REVISION = 'd7684c1dc4bcfd69708bbc013b251549ae40b1ca'

    def __init__(self):
        self._models_path = snapshot_download(repo_id=self.MODEL_REPO, revision=self.MODEL_REVISION)
        self._synthesizer = None

    def _get_synthesizer(self):
        # Load once per instance, not once per utterance.
        if self._synthesizer is None:
            models = Path(self._models_path)
            self._synthesizer = Synthesizer(
                tts_checkpoint=str(models / "glowtts/best_model_23590.pth"),
                tts_config_path=str(models / "glowtts/config.json"),
                vocoder_checkpoint=str(models / "hifigan/best_model_163888.pth"),
                vocoder_config=str(models / "hifigan/config.json"),
                use_cuda=False,
            )
        return self._synthesizer

    def tts(self, text: str, output_file_path: str):
        synthesizer = self._get_synthesizer()
        characters = synthesizer.tts_model.tokenizer.characters
        config = synthesizer.tts_config.characters
        allowed = set(config.characters + config.punctuations)
        unknown = set(text) - allowed
        if unknown:
            raise ValueError(f"Невядомыя для GlowTTS сімвалы фанем: {''.join(sorted(unknown))!r}")
        if not any(c in config.characters for c in text):
            raise ValueError("Тэкст не ўтрымлівае фанем для сінтэзу")
        # Check the actual tokenizer too: it otherwise silently drops unknowns.
        for char in text:
            characters.char_to_id(char)
        wavs = synthesizer.tts(text, split_sentences=False)
        synthesizer.save_wav(wavs, str(output_file_path))
