"""Local-weight sharding checks, without network or neural model imports."""
import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('prepare_moss',ROOT/'tools/browser_demo/prepare_moss.py')
preparation=importlib.util.module_from_spec(spec)
spec.loader.exec_module(preparation)


class ShardingTests(unittest.TestCase):
    def test_reassembles_exact_original_and_records_sizes_and_checksums(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'original';target=root/'out';target.mkdir()
            data=b'01234567'*(1024*1024)+b'tail';source.write_bytes(data)
            manifest=preparation.shard_weights(source,target,'weights.data')
            self.assertEqual(manifest['bytes'],len(data))
            self.assertEqual(len(manifest['parts']),2)
            chunks=[]
            for part in manifest['parts']:
                chunk=(target/part['path']).read_bytes();chunks.append(chunk)
                self.assertEqual(len(chunk),part['bytes'])
                self.assertLessEqual(len(chunk),8*1024*1024)
                self.assertEqual(hashlib.sha256(chunk).hexdigest(),part['sha256'])
            self.assertEqual(b''.join(chunks),data)

    def test_does_not_delete_a_modified_unsharded_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'original';source.write_bytes(b'original')
            target=root/'out';target.mkdir();old=target/'weights.data';old.write_bytes(b'user change')
            with self.assertRaisesRegex(ValueError,'modified'):
                preparation.shard_weights(source,target,'weights.data')
            self.assertEqual(old.read_bytes(),b'user change')


if __name__=='__main__':
    unittest.main()
