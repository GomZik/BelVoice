"""Export StressNoHomographs with the original reader and pinned BelG2P data.

No TTS models are loaded. Requires the same Java toolchain as build_g2p.py.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
JAR_URL = 'https://github.com/Belarus/BelG2P/releases/download/1.0.0/linguistics.BelG2P-1.0.0-jar-with-dependencies.jar'
JAR_SHA256 = '90bb034ec868e37e6e0e3646771a2dd874699d2c1c5142b71d8b2ffa3c7d9b80'


def sha256(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def export_dictionary(jar=None, output=None):
    build = ROOT / 'build/stress-dictionary'
    build.mkdir(parents=True, exist_ok=True)
    output = Path(output or ROOT / 'browser_demo/data/stresses-nohomographs.json.gz').resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    original = ROOT / 'tools/export_grammardb/src/main/java/GrammarDBStressReader.java'
    exporter = ROOT / 'tools/browser_demo/teavm/ExportStressDictionary.java'
    provenance = output.with_name('stresses-nohomographs-source.json')
    signature = {'jarSha256':JAR_SHA256, 'readerSha256':sha256(original), 'exporterSha256':sha256(exporter)}
    if jar is not None and sha256(jar) != JAR_SHA256:
        raise ValueError('Unexpected BelG2P 1.0.0 JAR checksum')
    if output.exists() and provenance.exists():
        previous = json.loads(provenance.read_text())
        if (all(previous.get(key) == value for key, value in signature.items())
                and previous.get('dictionarySha256') == sha256(output)):
            return output
    if jar is None:
        jar = build / 'belg2p-1.0.0.jar'
        if not jar.exists():
            urllib.request.urlretrieve(JAR_URL, jar)
    jar = Path(jar).resolve()
    if sha256(jar) != JAR_SHA256:
        raise ValueError('Unexpected BelG2P 1.0.0 JAR checksum')
    reader = original.read_text()
    old = 'db = GrammarDB2.initializeFromDir(dir);'
    assert reader.count(old) == 1, 'Original dictionary reader changed'
    # Only the data-loading location changes. SPELL → SHOW → ALL selection,
    # stress ambiguity and accepted-form filtering stay in the original reader.
    (build / 'GrammarDBStressReader.java').write_text(reader.replace(old, 'db = GrammarDB2.initializeFromJar();'))
    subprocess.run(['javac', '-encoding', 'UTF-8', '-cp', str(jar), '-d', str(build),
                    str(build / 'GrammarDBStressReader.java'), str(exporter)], check=True)
    subprocess.run(['java', '-Xmx3g', '-cp', os.pathsep.join([str(build), str(jar)]), 'ExportStressDictionary', str(output)], check=True)
    provenance.write_text(json.dumps({
        'belg2p': '1.0.0', 'dataUrl': JAR_URL,
        **signature,
        'dictionarySha256': sha256(output),
        'adaptation': 'initializeFromJar instead of developer-specific directory; unchanged original getNoHomographs algorithm',
    }, indent=2))
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--jar', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    print('Prepared stress dictionary:', export_dictionary(args.jar, args.output))


if __name__ == '__main__':
    main()
