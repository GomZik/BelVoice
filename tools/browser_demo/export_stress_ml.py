"""Export and verify the existing StressML weights (no retraining).

uv run --extra browser-demo python tools/browser_demo/export_stress_ml.py
"""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import onnx
import onnxruntime as ort
import torch

from belvoice.synth.stress.StressML import StressML, VOWELS
from belvoice.synth.stress.StressML_model import UNK_ID

ROOT = Path(__file__).resolve().parents[2]


def encode(segment, config):
    clipped = segment.lower()[-config['max_len']:]
    pad = config['max_len'] - len(clipped)
    return {
        'ids': np.array([[0] * pad + [config['char2id'].get(c, UNK_ID) for c in clipped]], dtype=np.int64),
        'pad_mask': np.array([[True] * pad + [False] * len(clipped)], dtype=bool),
        'vowel_mask': np.array([[False] * pad + [c in VOWELS for c in clipped]], dtype=bool),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'browser_demo/models')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    torch.set_num_threads(2)
    ml = StressML()
    resource = ROOT / 'framework/belvoice/synth/stress'
    config = json.loads((resource / 'stress_ml_config.json').read_text())
    encoded = encode('фанемізацыя', config)
    previous = torch.backends.mha.get_fastpath_enabled()
    try:
        # Export ordinary attention ops, not the fused inference-only Torch op.
        torch.backends.mha.set_fastpath_enabled(False)
        with torch.no_grad():
            torch.onnx.export(ml._model, tuple(torch.from_numpy(encoded[k]) for k in ['ids', 'pad_mask', 'vowel_mask']),
                              str(args.output / 'stress-ml.onnx'), input_names=['ids', 'pad_mask', 'vowel_mask'],
                              output_names=['logits'], opset_version=17, dynamo=False)
    finally:
        torch.backends.mha.set_fastpath_enabled(previous)
    onnx.checker.check_model(str(args.output / 'stress-ml.onnx'))
    options = ort.SessionOptions()
    options.intra_op_num_threads = 2
    session = ort.InferenceSession(str(args.output / 'stress-ml.onnx'), options, providers=['CPUExecutionProvider'])
    segments = ['прывітанне', 'беларускага', 'стрымерскі', 'рудзі', 'донаты', 'фанемізацыя',
                'неалагізмацыя', 'малпачка', 'Стрымерка', 'неверагоднасці', 'хтосьці',
                'абыякавасць', 'пераналаджванне', 'суперсінтэзатарскі', 'ааааа' * 12,
                'неймаверна' * 6, 'фэйкавае', 'незнаёмае', 'капіраванне']
    fixtures = []
    for segment in segments:
        feeds = encode(segment, config)
        logits = session.run(None, feeds)[0][0]
        with torch.no_grad():
            reference = ml._model(*(torch.from_numpy(feeds[k]) for k in ['ids', 'pad_mask', 'vowel_mask']))[0].numpy()
        np.testing.assert_allclose(logits, reference, atol=2e-4, rtol=2e-4)
        index, confidence = ml._predict_segment(segment)
        pad = config['max_len'] - min(len(segment), config['max_len'])
        offset = max(0, len(segment) - config['max_len'])
        predicted = int(np.argmax(logits)) - pad + offset
        assert predicted == index, (segment, predicted, index)
        probabilities = np.exp(logits - np.max(logits))
        probabilities /= probabilities.sum()
        np.testing.assert_allclose(float(probabilities.max()), confidence, atol=2e-5)
        stressed = segment[:index+1] + '\u0301' + segment[index+1:]
        fixtures.append({'segment': segment, 'stressed': stressed, 'index': index, 'confidence': confidence,
                         'max_logit_error': float(np.max(np.abs(logits-reference)))})
    browser_config = {**config, 'unk_id': UNK_ID, 'vowels': ''.join(sorted(VOWELS)),
                      'weights_sha256': hashlib.sha256((resource / 'stress_ml.safetensors').read_bytes()).hexdigest()}
    (args.output / 'stress-ml-config.json').write_text(json.dumps(browser_config, ensure_ascii=False, indent=2))
    (args.output / 'stress-ml-verification.json').write_text(json.dumps(fixtures, ensure_ascii=False, indent=2))
    print(f'Exported StressML: {(args.output / "stress-ml.onnx").stat().st_size / 2**20:.2f} MiB; {len(fixtures)} predictions verified against Python')


if __name__ == '__main__':
    main()
