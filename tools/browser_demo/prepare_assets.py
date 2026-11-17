"""Copy Python frontend data and the pinned local ONNX Runtime Web distribution."""

import hashlib
import json
from pathlib import Path
import tarfile
import urllib.request

from belvoice.synth.normalization.NormalizationSimple import NormalizationSimple

ROOT = Path(__file__).resolve().parents[2]
DEMO = ROOT / 'browser_demo'
ORT_VERSION = '1.31.1'


def main():
    vendor = DEMO / 'vendor'
    data = DEMO / 'data'
    vendor.mkdir(parents=True, exist_ok=True)
    data.mkdir(parents=True, exist_ok=True)
    archive = vendor / f'onnxruntime-web-{ORT_VERSION}.tgz'
    if not archive.exists():
        urllib.request.urlretrieve(f'https://registry.npmjs.org/onnxruntime-web/-/onnxruntime-web-{ORT_VERSION}.tgz', archive)
    files = ['dist/ort.wasm.min.mjs', 'dist/ort.wasm.min.mjs.map', 'dist/ort-wasm-simd-threaded.mjs',
             'dist/ort-wasm-simd-threaded.wasm']
    with tarfile.open(archive) as tar:
        for name in files:
            member = tar.extractfile('package/' + name)
            (vendor / Path(name).name).write_bytes(member.read())
    for name in ['LICENSE', 'ThirdPartyNotices.txt']:
        urllib.request.urlretrieve(f'https://raw.githubusercontent.com/microsoft/onnxruntime/v{ORT_VERSION}/{name}', vendor / name)
    (vendor / 'version.json').write_text(json.dumps({
        'package': 'onnxruntime-web', 'version': ORT_VERSION,
        'archive_sha256': hashlib.sha256(archive.read_bytes()).hexdigest(),
    }, indent=2))
    # No need to ship the package tarball alongside the runnable assets.
    archive.unlink()
    (data / 'normalization.json').write_text(json.dumps(NormalizationSimple.C2NAME, ensure_ascii=False))
    (data / 'stresses-stat.json').write_bytes((ROOT / 'framework/belvoice/synth/stress/stresses-stat.json').read_bytes())
    print('Prepared local runtime and frontend data:', DEMO)


if __name__ == '__main__':
    main()
