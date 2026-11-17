"""Prepare the optional OmniVoice browser backend and a fixed Belarusian prompt.

uv run --extra browser-demo python tools/browser_demo/prepare_omnivoice.py
--models wasm mirrors the large inference weights into models/omnivoice-browser
for local testing. They are NOT copied into the regular demo package.
"""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import re
import shutil
import tarfile
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / 'browser_demo/omni'
VOCO_REVISION = '7fa8601b9864005e473e14b41756d6e963211d97'
MODEL_REPO = 'Gigsu/vocoloco-onnx'
MODEL_REVISION = '2c301ff95a826f76ec9ff3d93233318f91362bf5'
ORT_VERSION = '1.30.0'


def replace_once(source, old, new):
    if source.count(old) != 1:
        raise ValueError(f'Unexpected upstream source: {old[:90]}')
    return source.replace(old, new, 1)


def download(url, target):
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        print('Download:', url, flush=True)
        urllib.request.urlretrieve(url, target)
    return target


def model_file(name):
    from huggingface_hub import hf_hub_download

    return Path(hf_hub_download(MODEL_REPO, filename=name, revision=MODEL_REVISION))


def disable_duration_headroom(source):
    # Match Python's target duration. VocoLoco's extra 12 frames reproduced a
    # repeated syllable in our fixed Belarusian voice at 16 steps; removing only
    # those frames resolved the user's exact reproducible sentence.
    return replace_once(source,
                        'const headroom = estimate < SHORT_TEXT_TOKENS ? HEADROOM_TOKENS : 0;',
                        'const headroom = 0; // BelVoice: original Python duration, no extra frames.')


def copy_model(source, target):
    # HF cache entries can be read-only. Do not preserve their permissions in
    # the writable local mirror, and make repeated preparation idempotent.
    if target.exists():
        if source.stat().st_size == target.stat().st_size:
            with source.open('rb') as a, target.open('rb') as b:
                if hashlib.file_digest(a, 'sha256').digest() == hashlib.file_digest(b, 'sha256').digest():
                    return
        target.unlink()
    shutil.copyfile(source, target)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--models', choices=['none', 'wasm', 'webgpu', 'both'], default='none')
    parser.add_argument('--grammar-jar', type=Path, help='Optional cached pinned BelG2P 1.0.0 JAR for the stress dictionary.')
    args = parser.parse_args()
    from export_stress_dictionary import export_dictionary

    # Finish dictionary export before importing/loading the audio model runtime.
    export_dictionary(args.grammar_jar)
    import numpy as np
    import onnxruntime as ort
    import soundfile as sf
    import torch
    import torchaudio

    cache = ROOT / 'build/omnivoice-downloads'
    OUTPUT.mkdir(parents=True, exist_ok=True)
    archive = download(f'https://github.com/Magkino/vocoloco_tts/archive/{VOCO_REVISION}.tar.gz', cache / 'vocoloco.tar.gz')
    vendor = OUTPUT / 'vendor/vocoloco'
    with tarfile.open(archive) as tar:
        for member in tar.getmembers():
            parts = Path(member.name).parts[1:]
            if not member.isfile() or not parts:
                continue
            relative = Path(*parts)
            include = (parts[0] == 'workers' and relative.suffix == '.js') or str(relative) in {
                'duration-estimator.js', 'sentence-buffer.js', 'audio-postprocess.js', 'time-stretch.js', 'LICENSE',
            }
            if include:
                target = vendor / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(tar.extractfile(member).read())
    worker = vendor / 'workers/tts-worker.js'
    source = worker.read_text()
    source = disable_duration_headroom(source)
    source = replace_once(source, "const CACHE_NAME = 'omnivoice-models-v1';", "const CACHE_NAME = 'belvoice-omnivoice-models-v1';")
    source = replace_once(source, "const TOKENIZER_CACHE = 'vocoloco-tokenizer-v1';", "const TOKENIZER_CACHE = 'belvoice-omnivoice-tokenizer-v1';")
    source = replace_once(source, "await caches.delete('transformers-cache').catch(() => {});", '// Do not delete caches owned by other applications.')
    source = replace_once(source, f"const ORT_CDN = 'https://cdn.jsdelivr.net/npm/onnxruntime-web@{ORT_VERSION}/dist/';",
                          "const ORT_CDN = new URL('../../ort/', import.meta.url).href;")
    source = replace_once(source, 'ort.env.wasm.numThreads = self.crossOriginIsolated ? (navigator.hardwareConcurrency || 4) : 1;',
                          'ort.env.wasm.numThreads = self.crossOriginIsolated ? Math.min(globalThis.belvoiceOmniThreads || 4, navigator.hardwareConcurrency || 1) : 1;')
    source = replace_once(source, 'forceCPU = false, confirmDownload = false, lowMemory: lm = false, probeBytes = 0',
                          "forceCPU = false, backend = 'wasm', confirmDownload = false, lowMemory: lm = false, probeBytes = 0")
    source = replace_once(source, 'const adapter = forceCPU ? null : await engineAdapter();',
                          "const adapter = forceCPU ? null : await engineAdapter();\n    if (backend === 'webgpu' && !adapter) throw new Error('WebGPU with shader-f16 is required; select WASM explicitly instead.');")
    if source.count('if (lowMemory) throw e;') != 2:
        raise ValueError('Unexpected WebGPU fallback source')
    source = source.replace('if (lowMemory) throw e;', "if (lowMemory || backend === 'webgpu') throw e;")
    source = replace_once(source, 'const encoderInfo = await inspectFile(await caches.open(CACHE_NAME), encoderUrl).catch(() => null);',
                          'const encoderInfo = null; // BelVoice ships pre-encoded reference tokens; no encoder request.')
    source = replace_once(source, "type: 'ready', backend, encoderAvailable: true,", "type: 'ready', backend, encoderAvailable: false,")
    # Avoid leaking ORT output/feed tensors between repeated generations.
    source = replace_once(source, "const r = await decoderSession.run({ audio_codes: new ort.Tensor('int64', codes, [1, C, T]) });\n  return r.audio_values.data;",
                          "const input = new ort.Tensor('int64', codes, [1, C, T]);\n  let r;\n  try {\n    r = await decoderSession.run({audio_codes: input});\n    return Float32Array.from(r.audio_values.data);\n  } finally {\n    input.dispose();\n    if (r) for (const t of Object.values(r)) t.dispose();\n  }")
    source = replace_once(source, '  const sched = unmaskSchedule(nPos, numStep, tShift);',
                          '  const sched = unmaskSchedule(nPos, numStep, tShift);\n  try {')
    source = replace_once(source, '  return tokens;\n}\n\n// ─── Decode',
                          '  return tokens;\n  } finally {\n    for (const feed of passes.feeds ?? []) for (const t of Object.values(feed)) t.dispose();\n  }\n}\n\n// ─── Decode')
    worker.write_text(source)
    files_module = vendor / 'workers/model-files.js'
    files_module.write_text(replace_once(files_module.read_text(), "const DISK_DIR = 'vl-models';", "const DISK_DIR = 'belvoice-omnivoice-models';"))
    # Keep the TTS dependency closure, not unrelated ASR/UI workers. No Whisper
    # runtime is needed by this fixed-reference integration.
    needed, pending = set(), [worker.resolve()]
    while pending:
        path = pending.pop()
        if path in needed:
            continue
        needed.add(path)
        imports = re.findall(r"\b(?:from\s*|import\s*\(\s*|import\s*)['\"](\.[^'\"]+)['\"]", path.read_text())
        for relative in imports:
            dependency = (path.parent / relative.split('?')[0]).resolve()
            if dependency.suffix == '.js':
                if not dependency.is_relative_to(vendor.resolve()) or not dependency.is_file():
                    raise ValueError(f'Missing vendor dependency: {dependency}')
                pending.append(dependency)
    for path in vendor.rglob('*.js'):
        if path.resolve() not in needed:
            path.unlink()

    runtime = download(f'https://registry.npmjs.org/onnxruntime-web/-/onnxruntime-web-{ORT_VERSION}.tgz', cache / 'ort.tgz')
    ort_out = OUTPUT / 'vendor/ort'
    ort_out.mkdir(parents=True, exist_ok=True)
    runtime_files = ['ort.webgpu.min.mjs', 'ort-wasm-simd-threaded.asyncify.mjs', 'ort-wasm-simd-threaded.asyncify.wasm']
    with tarfile.open(runtime) as tar:
        for member in tar.getmembers():
            name = Path(member.name).name
            if member.isfile() and name in runtime_files:
                (ort_out / name).write_bytes(tar.extractfile(member).read())
    # Discard unused variants left by earlier builds, not arbitrary user files.
    for path in ort_out.glob('ort-wasm-*'):
        if path.name not in runtime_files and path.suffix in ['.mjs', '.wasm']:
            path.unlink()
    for name in ['LICENSE', 'ThirdPartyNotices.txt']:
        path = download(f'https://raw.githubusercontent.com/microsoft/onnxruntime/v{ORT_VERSION}/{name}', cache / name)
        shutil.copy2(path, ort_out / name)

    for name in ['README.md', 'LICENSE-higgs-audio-2', 'LICENSE-llama-3', 'LICENSE-qwen', 'NOTICE']:
        shutil.copy2(model_file(name), OUTPUT / name)
    text_source = ROOT / 'framework/belvoice/synth/tts/TTSOmniVoice.py'
    tree = ast.parse(text_source.read_text())
    ref_text = next(ast.literal_eval(node.value) for node in tree.body if isinstance(node, ast.Assign)
                    and any(isinstance(target, ast.Name) and target.id == '_REF_TEXT' for target in node.targets))
    ref_audio = ROOT / 'framework/belvoice/synth/tts/tts-omnivoice/ref.wav'
    torch.set_num_threads(2)
    audio, sample_rate = sf.read(ref_audio, dtype='float32', always_2d=True)
    audio = torch.from_numpy(audio.mean(axis=1)).unsqueeze(0)
    audio = torchaudio.functional.resample(audio, sample_rate, 24000).numpy()
    rms = float(np.sqrt(np.mean(audio**2)))
    if 0 < rms < 0.1:
        audio = audio * (0.1 / rms)
    audio = np.ascontiguousarray(audio[:, :audio.shape[-1] // 960 * 960][None], dtype=np.float32)
    print('Encoding the existing Belarusian reference:', audio.shape[-1] / 24000, 's', flush=True)
    options = ort.SessionOptions()
    options.intra_op_num_threads = 2
    session = ort.InferenceSession(str(model_file('omnivoice-encoder-fixed.onnx')), options, providers=['CPUExecutionProvider'])
    codes = session.run(['audio_codes'], {'input_values': audio})[0]
    assert codes.shape[0:2] == (1, 8) and codes.shape[2] == audio.shape[-1] // 960
    assert np.all((codes >= 0) & (codes < 1024))
    prompt = {'refText': ref_text, 'refTokens': codes.reshape(-1).astype(int).tolist(),
              'numCodebooks': 8, 'tokenCount': codes.shape[2], 'sampleRate': 24000,
              'duration': audio.shape[-1] / 24000, 'sourceRms': rms,
              'audioSha256': hashlib.sha256(ref_audio.read_bytes()).hexdigest(),
              'preprocessing': 'mono, torchaudio resample 24kHz, RMS >=0.1, hop=960; no silence removal (full transcript preserved)',
              'source': 'framework/belvoice/synth/tts/TTSOmniVoice.py and tts-omnivoice/ref.wav'}
    (OUTPUT / 'reference.json').write_text(json.dumps(prompt, ensure_ascii=False))
    provenance = {'vocolocoRevision': VOCO_REVISION, 'modelsRepo': MODEL_REPO, 'modelsRevision': MODEL_REVISION,
                  'modelBaseUrl': f'https://huggingface.co/{MODEL_REPO}/resolve/{MODEL_REVISION}',
                  'ortVersion': ORT_VERSION, 'sourceArchiveSha256': hashlib.sha256(archive.read_bytes()).hexdigest(),
                  'adaptations': ['local ORT imports', 'bounded WASM threads', 'explicit WebGPU failure (no larger WASM auto-download)',
                                  'no voice encoder probe', 'copy and release decoder tensors', 'release generation input tensors',
                                   'BelVoice-specific caches; no deletion of unrelated app caches',
                                   'original Python target duration; disable VocoLoco short-text headroom']}
    (OUTPUT / 'source.json').write_text(json.dumps(provenance, indent=2))
    if args.models != 'none':
        names = ['omnivoice-config.json', 'tokenizer.json']
        if args.models in ['wasm', 'both']:
            names += ['omnivoice-main-split.onnx', 'omnivoice-decoder.onnx', 'omnivoice-main-manifest.json']
            names += json.loads(model_file('omnivoice-main-manifest.json').read_text())
        if args.models in ['webgpu', 'both']:
            names += [f'engine/{name}{suffix}' for name in ['omnivoice-f16', 'decoder-f32'] for suffix in ['.json', '.bin']]
        mirror = ROOT / 'models/omnivoice-browser'
        for name in names:
            path = mirror / name
            path.parent.mkdir(parents=True, exist_ok=True)
            copy_model(model_file(name), path)
        print('Local inference weights:', mirror, flush=True)
    print('Optional OmniVoice resources ready:', OUTPUT, flush=True)


if __name__ == '__main__':
    main()
