"""Dictionary build reproducibility, without Java, network or model weights."""
import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('export_stress_dictionary', ROOT / 'tools/browser_demo/export_stress_dictionary.py')
exporter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(exporter)


class DictionaryExportTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.reader = self.root / 'tools/export_grammardb/src/main/java/GrammarDBStressReader.java'
        self.reader.parent.mkdir(parents=True)
        self.reader.write_text('db = GrammarDB2.initializeFromDir(dir);')
        self.java = self.root / 'tools/browser_demo/teavm/ExportStressDictionary.java'
        self.java.parent.mkdir(parents=True)
        self.java.write_text('fixture exporter')
        self.jar = self.root / 'pinned.jar'
        self.jar.write_bytes(b'fixture jar')
        self.output = self.root / 'dictionary.json.gz'
        self.addCleanup(patch.stopall)
        patch.object(exporter, 'ROOT', self.root).start()
        patch.object(exporter, 'JAR_SHA256', hashlib.sha256(self.jar.read_bytes()).hexdigest()).start()

    def build(self):
        def run(command, **kwargs):
            if command[0] == 'java':
                self.output.write_bytes(b'generated dictionary fixture')
        with patch.object(exporter.subprocess, 'run', side_effect=run) as mock:
            exporter.export_dictionary(self.jar, self.output)
            return mock.call_count

    def test_build_preserves_original_reader_and_reuses_verified_output(self):
        self.assertEqual(self.build(), 2)
        self.assertEqual(self.reader.read_text(), 'db = GrammarDB2.initializeFromDir(dir);')
        self.assertIn('initializeFromJar()', (self.root / 'build/stress-dictionary/GrammarDBStressReader.java').read_text())
        self.assertEqual(self.build(), 0)
        with patch.object(exporter.urllib.request, 'urlretrieve', side_effect=AssertionError('No download')):
            self.assertEqual(exporter.export_dictionary(output=self.output), self.output)

    def test_changed_dictionary_or_exporter_invalidates_cache(self):
        self.build()
        self.output.write_bytes(b'corrupted')
        self.assertEqual(self.build(), 2)
        self.java.write_text('updated fixture exporter')
        self.assertEqual(self.build(), 2)

    def test_rejects_wrong_source_jar_even_with_valid_cached_output(self):
        self.build()
        self.jar.write_bytes(b'wrong jar')
        with self.assertRaisesRegex(ValueError, 'checksum'):
            self.build()


if __name__ == '__main__':
    unittest.main()
