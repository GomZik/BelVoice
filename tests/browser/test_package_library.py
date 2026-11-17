"""Safety checks for refreshing generated distribution folders."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('package_library', ROOT / 'tools/browser_demo/package_library.py')
packaging = importlib.util.module_from_spec(spec)
spec.loader.exec_module(packaging)


class PackageValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        manifest = {}
        for name in ['belvoice.js', 'package.json', 'worker.js']:
            data = name.encode()
            (self.root / name).write_bytes(data)
            manifest[name] = {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
        (self.root / 'manifest.json').write_text(json.dumps(manifest))

    def test_accepts_unchanged_generated_package(self):
        packaging.validate_package(self.root)

    def test_refuses_extra_user_file(self):
        (self.root / 'notes.txt').write_text('keep me')
        with self.assertRaises(ValueError):
            packaging.validate_package(self.root)
        self.assertTrue((self.root / 'notes.txt').exists())

    def test_refuses_modified_file_even_with_same_size(self):
        (self.root / 'worker.js').write_text('WORKER.JS')
        with self.assertRaises(ValueError):
            packaging.validate_package(self.root)

    def test_refuses_missing_file(self):
        (self.root / 'worker.js').unlink()
        with self.assertRaises(ValueError):
            packaging.validate_package(self.root)

    def test_refuses_symlink(self):
        (self.root / 'worker.js').unlink()
        (self.root / 'worker.js').symlink_to(self.root / 'belvoice.js')
        with self.assertRaises(ValueError):
            packaging.validate_package(self.root)


if __name__ == '__main__':
    unittest.main()
