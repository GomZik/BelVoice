"""Lightweight regression checks: no model imports or weight downloads."""
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('prepare_omnivoice', ROOT / 'tools/browser_demo/prepare_omnivoice.py')
preparation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preparation)


class DurationHeadroomTests(unittest.TestCase):
    def test_disables_extra_frames_without_changing_estimate_or_limit(self):
        source = '''const estimate = estimateTargetTokens(text, estRefText, estRefTokens, speed);
const headroom = estimate < SHORT_TEXT_TOKENS ? HEADROOM_TOKENS : 0;
let numTargetTokens = Math.min(estimate + headroom, 700);'''
        patched = preparation.disable_duration_headroom(source)
        self.assertIn('const headroom = 0;', patched)
        self.assertEqual(source.splitlines()[0], patched.splitlines()[0])
        self.assertEqual(source.splitlines()[-1], patched.splitlines()[-1])
        self.assertNotIn('estimate < SHORT_TEXT_TOKENS', patched)

    def test_rejects_changed_or_duplicate_upstream_code(self):
        line = 'const headroom = estimate < SHORT_TEXT_TOKENS ? HEADROOM_TOKENS : 0;'
        for source in ['', line + '\n' + line]:
            with self.subTest(source=source), self.assertRaises(ValueError):
                preparation.disable_duration_headroom(source)


if __name__ == '__main__':
    unittest.main()
