"""Export the existing checkpoints; no training or checkpoint modifications.

uv run --extra browser-demo python tools/browser_demo/export_models.py
"""

import argparse
import json
from pathlib import Path
import tempfile

import numpy as np
import onnx
import onnxruntime as ort
import torch

from belvoice.synth.tts.TTSCoquiTTS import TTSCoquiTTS


class Encoder(torch.nn.Module):
    def __init__(self, model):
        super().__init__()
        self.encoder = model.encoder

    def forward(self, tokens, lengths):
        mean, log_scale, log_duration, mask = self.encoder(tokens, lengths, g=None)
        return mean, log_scale, log_duration


class Decoder(torch.nn.Module):
    def __init__(self, model):
        super().__init__()
        self.decoder = model.decoder

    def forward(self, z):
        mask = torch.ones_like(z[:, :1, :])
        mel, _ = self.decoder(z, mask, g=None, reverse=True)
        return mel


class Vocoder(torch.nn.Module):
    def __init__(self, model, clip=True):
        super().__init__()
        self.model = model
        self.clip = clip

    def forward(self, mel):
        # The two audio configs are identical; denormalize -> normalize is
        # equivalent to clipping to [-max_norm, max_norm].
        return self.model.inference(torch.clamp(mel, -4, 4) if self.clip else mel)


def export(module, args, path, inputs, outputs, axes):
    module.eval()
    # The legacy exporter supports these convolutional models and dynamic
    # sequence axes without requiring data-dependent torch.export shapes.
    torch.onnx.export(module, args, str(path), input_names=inputs,
                      output_names=outputs, dynamic_axes=axes,
                      opset_version=17, dynamo=False)
    onnx.checker.check_model(str(path))
    print(f"Exported {path}: {path.stat().st_size / 2**20:.1f} MiB", flush=True)


@torch.inference_mode()
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path)
    parser.add_argument('--voice', choices=['default', 'female-1'], default='default')
    args = parser.parse_args()
    if args.output is None:
        args.output = Path('browser_demo/models') if args.voice == 'default' else Path('browser_demo/models/female-1')
    args.output.mkdir(parents=True, exist_ok=True)
    torch.set_num_threads(2)
    if args.voice == 'default':
        engine = TTSCoquiTTS()
        s = engine._get_synthesizer()
        source = Path(engine._models_path)
        repo, revision, license_name = 'alex73/BelarusianTTSviaCoquiTTS', source.name, 'Apache-2.0'
        checkpoints = ['glowtts/best_model_23590.pth', 'hifigan/best_model_163888.pth']
    else:
        from huggingface_hub import snapshot_download
        from TTS.utils.synthesizer import Synthesizer
        repo, revision, license_name = 'slapula/commonvoice_be_tts_female_1', '95b899d31a13278364b85b88f953e92df2ff4826', 'MIT'
        checkpoints = ['best_model.pth', 'vocoder_best_model.pth']
        source = Path(snapshot_download(repo, revision=revision))
        # Resolve the relative statistics path in temporary config copies only.
        # Original HF checkpoints and configs are never modified.
        with tempfile.TemporaryDirectory(prefix='belvoice-config-') as tmp:
            for name in ['config.json', 'vocoder_config.json']:
                cfg = json.loads((source / name).read_text())
                cfg['audio']['stats_path'] = str(source / 'scale_stats_female_1.npy')
                (Path(tmp) / name).write_text(json.dumps(cfg))
            s = Synthesizer(tts_checkpoint=str(source / checkpoints[0]), tts_config_path=str(Path(tmp) / 'config.json'),
                            vocoder_checkpoint=str(source / checkpoints[1]), vocoder_config=str(Path(tmp) / 'vocoder_config.json'),
                            use_cuda=False)
    model = s.tts_model.eval()
    # Synthesizer.load_checkpoint(eval=True) already stores inverse flow weights
    # and removes weight normalization; calling store_inverse twice is invalid.
    assert model.inference_noise_scale == 0, 'Export currently expects this deterministic checkpoint'
    assert s.tts_config.audio.to_dict() == s.vocoder_config.audio.to_dict()
    has_stats = hasattr(s.tts_model.ap, 'mel_scaler')
    if not has_stats:
        assert s.tts_model.ap.stats_path is None and s.tts_model.ap.max_norm == 4
    if has_stats:
        # Equal mean/variance scalers cancel exactly; do not clamp stats-normalized mel.
        np.testing.assert_array_equal(s.tts_model.ap.mel_scaler.mean_, s.vocoder_ap.mel_scaler.mean_)
        np.testing.assert_array_equal(s.tts_model.ap.mel_scaler.scale_, s.vocoder_ap.mel_scaler.scale_)
    tokenizer = model.tokenizer
    modules = {'encoder': Encoder(model), 'decoder': Decoder(model), 'vocoder': Vocoder(s.vocoder_model, clip=not has_stats)}
    tokens = torch.tensor([tokenizer.text_to_ids('jˈɔn atkazˈau̯')], dtype=torch.long)
    lengths = torch.tensor([tokens.shape[1]])
    export(modules['encoder'], (tokens, lengths), args.output / 'encoder.onnx',
           ['tokens', 'lengths'], ['mean', 'log_scale', 'log_duration'],
           {'tokens': {1: 'tokens'}, 'mean': {2: 'tokens'},
            'log_scale': {2: 'tokens'}, 'log_duration': {2: 'tokens'}})
    z = torch.zeros(1, 80, 100)
    export(modules['decoder'], (z,), args.output / 'decoder.onnx', ['z'], ['mel'],
           {'z': {2: 'frames'}, 'mel': {2: 'frames'}})
    export(modules['vocoder'], (z,), args.output / 'vocoder.onnx', ['mel'], ['audio'],
           {'mel': {2: 'frames'}, 'audio': {2: 'samples'}})

    characters = tokenizer.characters
    metadata = {
        'sample_rate': s.output_sample_rate, 'mel_channels': 80,
        'length_scale': model.length_scale, 'noise_scale': model.inference_noise_scale,
        'squeeze': model.decoder.num_squeeze,
        'char_to_id': {characters.id_to_char(i): i for i in range(characters.num_chars)},
        'blank_id': characters.blank_id, 'bos_id': characters.bos_id, 'eos_id': characters.eos_id,
        'add_blank': tokenizer.add_blank, 'use_eos_bos': tokenizer.use_eos_bos,
        'checkpoint_repo': repo,
        'checkpoint_revision': revision,
        'voice': args.voice,
        'mel_normalization': 'mean-variance' if has_stats else 'range',
    }
    (args.output / 'config.json').write_text(json.dumps(metadata, ensure_ascii=False, indent=2))
    (args.output / 'MODEL_CARD.md').write_bytes((source / 'README.md').read_bytes())
    (args.output / 'MODEL_SOURCE.json').write_text(json.dumps({
        'url': f'https://huggingface.co/{repo}',
        'revision': metadata['checkpoint_revision'],
        'license_in_model_card': license_name,
        'checkpoints': checkpoints,
    }, indent=2))
    options = ort.SessionOptions()
    options.intra_op_num_threads = 2
    sessions = {name: ort.InferenceSession(str(args.output / f'{name}.onnx'), options,
                                         providers=['CPUExecutionProvider']) for name in modules}
    report = []
    for phonemes in ['jˈɔn', 'jˈɔn atkazˈau̯', 'prɨvʲitˈanʲːɛ! ɣˈɛta pravʲˈɛrka.']:
        ids = np.array([tokenizer.text_to_ids(phonemes)], dtype=np.int64)
        lens = np.array([ids.shape[1]], dtype=np.int64)
        mean, logs, log_dur = sessions['encoder'].run(None, {'tokens': ids, 'lengths': lens})
        durations = np.maximum(np.ceil((np.exp(log_dur) - 1) * model.length_scale), 1).astype(int).reshape(-1)
        expanded = np.repeat(mean, durations, axis=2)
        expanded = expanded[:, :, :expanded.shape[2] // metadata['squeeze'] * metadata['squeeze']]
        mel = sessions['decoder'].run(None, {'z': expanded})[0]
        audio = sessions['vocoder'].run(None, {'mel': mel})[0]
        with torch.inference_mode():
            reference_mel = model.inference(torch.from_numpy(ids), {'x_lengths': torch.from_numpy(lens)})['model_outputs'].transpose(1, 2)
            reference_audio = modules['vocoder'](reference_mel).numpy()
        np.testing.assert_allclose(mel, reference_mel.numpy(), atol=3e-3, rtol=3e-3)
        # Tiny mel differences get amplified by the vocoder: report waveform
        # error, also compare each exported stage independently below.
        direct_audio = modules['vocoder'](torch.from_numpy(mel)).detach().numpy()
        normalized = s.vocoder_ap.normalize(s.tts_model.ap.denormalize(mel[0]))
        expected_mel = mel[0] if has_stats else np.clip(mel[0], -4, 4)
        np.testing.assert_allclose(normalized, expected_mel, atol=2e-5)
        np.testing.assert_allclose(audio, direct_audio, atol=3e-3, rtol=3e-3)
        entry = {'phonemes': phonemes, 'tokens': ids.shape[1], 'frames': mel.shape[2],
                 'samples': audio.size, 'mel_max_error': float(np.max(np.abs(mel-reference_mel.numpy()))),
                 'audio_rmse': float(np.sqrt(np.mean((audio-reference_audio)**2)))}
        print('Verified dynamic shapes:', entry, flush=True)
        report.append(entry)
    (args.output / 'verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
