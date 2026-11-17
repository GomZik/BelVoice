"""Make a self-contained, UI-free static library directory. No model rebuilding.

uv run python tools/browser_demo/package_library.py
Copy dist/belvoice/ to the other project's public/belvoice/ directory.
"""

import argparse
import hashlib
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'browser_demo'


def validate_package(output):
    """Refuse to replace/remove a package with modified or extra user files."""
    if output.is_symlink() or not (output / 'manifest.json').is_file():
        raise ValueError(f'Not a generated package directory: {output}')
    manifest = json.loads((output / 'manifest.json').read_text())
    if not {'belvoice.js', 'package.json', 'worker.js'} <= manifest.keys():
        raise ValueError(f'Not a BelVoice package: {output}')
    paths = list(output.rglob('*'))
    if any(path.is_symlink() for path in paths):
        raise ValueError(f'Package contains symlinks: {output}')
    actual = {str(path.relative_to(output)) for path in paths if path.is_file()}
    if actual != set(manifest) | {'manifest.json'}:
        raise ValueError(f'Package has missing or extra files: {output}')
    for name, expected in manifest.items():
        path = output / name
        if path.stat().st_size != expected['bytes']:
            raise ValueError(f'Modified generated file: {path}')
        with path.open('rb') as stream:
            if hashlib.file_digest(stream, 'sha256').hexdigest() != expected['sha256']:
                raise ValueError(f'Modified generated file: {path}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--demo', action='store_true', help='Include the demo page and Netlify isolation headers.')
    parser.add_argument('--omnivoice', action='store_true', help='Include prepared optional OmniVoice worker/runtime/reference resources (not large inference weights).')
    parser.add_argument('--moss', action='store_true', help='Include the complete local MOSS-TTS-Nano inference weights and runtime assets.')
    parser.add_argument('--refresh', action='store_true', help='Replace an existing generated package only if all manifest checks pass.')
    args = parser.parse_args()
    requested = args.output or ROOT / ('dist/belvoice-demo' if args.demo else 'dist/belvoice')
    if requested.is_symlink():
        parser.error('Output must not be a symlink')
    output = requested.resolve()
    if output == SOURCE or SOURCE in output.parents or output in SOURCE.parents:
        parser.error('Output must not overlap the browser_demo source directory')
    if output.exists() and any(output.iterdir()):
        if not args.refresh:
            parser.error(f'Output is not empty: {output}. Use --refresh to update a verified generated package.')
        try:
            validate_package(output)
        except (ValueError, OSError) as error:
            parser.error(str(error))
    required = ['models/encoder.onnx', 'models/decoder.onnx', 'models/vocoder.onnx',
                'models/config.json', 'g2p/belg2p.mjs', 'g2p/grammar.json.gz',
                'vendor/ort.wasm.min.mjs', 'vendor/ort-wasm-simd-threaded.wasm',
                 'data/normalization.json', 'data/stresses-stat.json', 'models/stress-ml.onnx', 'models/stress-ml-config.json']
    required += [f'models/female-1/{name}' for name in ['config.json','encoder.onnx','decoder.onnx','vocoder.onnx','verification.json']]
    if args.omnivoice:
        required += ['omni/reference.json','omni/source.json','omni/vendor/vocoloco/workers/tts-worker.js','omni/vendor/ort/ort.webgpu.min.mjs',
                     'data/stresses-nohomographs.json.gz','data/stresses-nohomographs-source.json']
    if args.moss:
        required += ['moss/reference.json','moss/manifest.json','moss/weights.json','moss/source.json',
                     'moss/vendor/tokenizers.mjs','moss/vendor/time-stretch.js','moss/LICENSE-MOSS',
                     'data/stresses-nohomographs.json.gz','data/stresses-nohomographs-source.json']
        weights_path=SOURCE/'moss/weights.json'
        if weights_path.is_file():
            for name,weight in json.loads(weights_path.read_text()).items():
                folder=Path(name).parent
                for part in weight['parts']:
                    path=SOURCE/'moss'/folder/part['path']
                    if not path.resolve().is_relative_to((SOURCE/'moss').resolve()):
                        parser.error('Invalid MOSS weight shard path')
                    if not path.is_file() or path.stat().st_size!=part['bytes']:
                        parser.error(f'Missing/incomplete MOSS weight shard: {path}')
                    with path.open('rb') as stream:
                        if hashlib.file_digest(stream,'sha256').hexdigest()!=part['sha256']:
                            parser.error(f'Modified MOSS weight shard: {path}')
                if sum(part['bytes'] for part in weight['parts'])!=weight['bytes']:
                    parser.error(f'Invalid MOSS weight size: {name}')
        required += [f'moss/{folder}/{name}' for folder,names in {
            'tts':['moss_tts_prefill.onnx','moss_tts_decode_step.onnx','moss_tts_local_fixed_sampled_frame.onnx'],
            'codec':['moss_audio_tokenizer_decode_full.onnx']}.items() for name in names]
    for name in required:
        if not (SOURCE / name).is_file():
            parser.error(f'Missing {name}; build the browser demo assets first (see browser_demo/README.md).')
    # Inputs and every existing output file have been checked before deletion.
    if output.exists() and args.refresh:
        shutil.rmtree(output)
    output.mkdir(parents=True, exist_ok=True)
    for name in ['belvoice.js', 'belvoice.d.ts', 'worker.js', 'frontend.js', 'number-words.js', 'runtime-config.js', 'stress-ml.js', 'stress-predictor.js', 'stress-pipeline.js', 'omnivoice.js', 'omnivoice-worker.js', 'omnivoice-text-worker.js', 'moss-core.js', 'moss-worker.js', 'package.json']:
        shutil.copy2(SOURCE / name, output / name)
    for name in ['models', 'g2p', 'vendor', 'data']:
        ignore = shutil.ignore_patterns('stresses-nohomographs*') if name == 'data' and not (args.omnivoice or args.moss) else None
        shutil.copytree(SOURCE / name, output / name, ignore=ignore)
    if args.omnivoice:
        shutil.copytree(SOURCE / 'omni', output / 'omni')
    if args.moss:
        shutil.copytree(SOURCE / 'moss', output / 'moss')
    shutil.copy2(SOURCE / 'LIBRARY.md', output / 'README.md')
    shutil.copy2(SOURCE / 'OMNIVOICE.md', output / 'OMNIVOICE.md')
    shutil.copy2(SOURCE / 'MOSS.md', output / 'MOSS.md')
    shutil.copy2(ROOT / 'LICENSE.md', output / 'LICENSE.md')
    if args.demo:
        for name in ['index.html', 'app.js', 'style.css', '_headers']:
            shutil.copy2(SOURCE / name, output / name)
        if not args.omnivoice:
            page = output / 'index.html'
            page.write_text(page.read_text().replace('<option value="omnivoice">', '<option value="omnivoice" disabled>'))
        if not args.moss:
            page = output / 'index.html'
            page.write_text(page.read_text().replace('<option value="moss">', '<option value="moss" disabled>'))
    shutil.copytree(ROOT / 'integrations/gleam', output / 'integrations/gleam',
                    ignore=shutil.ignore_patterns('build', '.git', 'manifest.toml'))
    manifest = {}
    for path in sorted(output.rglob('*')):
        if path.is_file():
            with path.open('rb') as stream:
                digest = hashlib.file_digest(stream, 'sha256').hexdigest()
            manifest[str(path.relative_to(output))] = {'bytes': path.stat().st_size, 'sha256': digest}
    (output / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    size = sum(item['bytes'] for item in manifest.values()) / 2**20
    kind = 'Static demo with Netlify headers' if args.demo else 'Library without HTML'
    print(f'Ready: {output} ({size:.1f} MiB, {len(manifest)} files). {kind}; no server-side synthesis.')


if __name__ == '__main__':
    main()
