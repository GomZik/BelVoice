"""Prepare a fully local, optional MOSS-TTS-Nano browser backend.

uv run --locked --extra browser-demo python tools/browser_demo/prepare_moss.py
All inference files are packaged locally; the encoder is build-time only.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tarfile
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / 'browser_demo/moss'
TTS_REPO = 'OpenMOSS-Team/MOSS-TTS-Nano-100M-ONNX'
TTS_REVISION = 'f52645cb467506d8e18e746ddd59482685b74e58'
CODEC_REPO = 'OpenMOSS-Team/MOSS-Audio-Tokenizer-Nano-ONNX'
CODEC_REVISION = 'ceff0d0749bfb3fa2d61149794ec6feef0d1e1ae'
SOURCE_REVISION = '8b7bcc9341b3b4ef3a3a58ba1338a7d85ff133eb'
TOKENIZERS_VERSION = '0.2.0'
VOCO_REVISION = '7fa8601b9864005e473e14b41756d6e963211d97'


def download(url, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        temporary = path.with_suffix(path.suffix + '.part')
        urllib.request.urlretrieve(url, temporary)
        temporary.replace(path)
    return path


def model_file(repo, revision, name):
    from huggingface_hub import hf_hub_download
    return Path(hf_hub_download(repo, filename=name, revision=revision))


def shard_weights(source, target, name):
    """Keep local static files <=8 MiB instead of one 440 MB CDN object."""
    parts=[]
    with source.open('rb') as stream:
        index=0
        while chunk:=stream.read(8*1024*1024):
            filename=f'{name}.{index:03d}'
            (target/filename).write_bytes(chunk)
            parts.append({'path':filename,'bytes':len(chunk),'sha256':hashlib.sha256(chunk).hexdigest()})
            index+=1
    old=target/name
    if old.exists():
        with old.open('rb') as a,source.open('rb') as b:
            if hashlib.file_digest(a,'sha256').digest()!=hashlib.file_digest(b,'sha256').digest():
                raise ValueError(f'Refusing to remove modified unsharded weights: {old}')
        old.unlink()
    return {'bytes':source.stat().st_size,'parts':parts}


def prepare_tokenizer(model_path):
    import sentencepiece as spm
    from sentencepiece import sentencepiece_model_pb2
    from tokenizers import AddedToken, Regex, Tokenizer, models, normalizers, pre_tokenizers
    from transformers.tokenization_utils_base import generate_merges

    proto=sentencepiece_model_pb2.ModelProto()
    proto.ParseFromString(model_path.read_bytes())
    assert proto.trainer_spec.model_type==2 and proto.trainer_spec.byte_fallback
    vocab={piece.piece:i for i,piece in enumerate(proto.pieces)}
    merges=generate_merges(vocab,{piece.piece:piece.score for piece in proto.pieces})
    tokenizer=Tokenizer(models.BPE(vocab,merges,unk_token=proto.trainer_spec.unk_piece,byte_fallback=True,fuse_unk=True))
    tokenizer.add_tokens([AddedToken(p.piece,normalized=False,special=p.type==3) for p in proto.pieces if p.type in [3,4]])
    tokenizer.normalizer=normalizers.Sequence([normalizers.Precompiled(proto.normalizer_spec.precompiled_charsmap),
        normalizers.Strip(left=True,right=True),normalizers.Replace(Regex(' {2,}'),' ')])
    tokenizer.pre_tokenizer=pre_tokenizers.Metaspace(replacement='▁',prepend_scheme='always')
    tokenizer.save(str(OUTPUT / 'tokenizer.json'))
    original = spm.SentencePieceProcessor(model_file=str(model_path))
    texts = ['Прывітанне! Гэта праверка беларускага сінтэзу маўлення.',
             'Прывіта́нне! Гэ́та праве́рка.', 'Ў ў І і Ё ё', 'Крыптавалю́та.',
             'адна́ ты́сяча', 'ма́ма', 'Hello world!', 'Dzień dobry!', 'Добрый день!',
             'На некаторых фестывалях семʼі з маленькімі дзецьмі.', '', '  а\tб\nв  ',
             '«Беларусь» — гэта мы. 🙂']
    statistics=json.loads((ROOT/'framework/belvoice/synth/stress/stresses-stat.json').read_text())
    texts+=list(statistics)[:256]+list(statistics.values())[:256]
    fixtures = [{'text':text,'ids':original.encode(text)} for text in texts]
    for row in fixtures:
        assert tokenizer.encode(row['text'], add_special_tokens=False).ids == row['ids'], row['text']
    script = """import fs from 'node:fs';
const root=process.argv[1];
const {Tokenizer}=await import('file://'+root+'/vendor/tokenizers.mjs');
const tok=new Tokenizer(JSON.parse(fs.readFileSync(root+'/tokenizer.json','utf8')),{});
const fixtures=JSON.parse(fs.readFileSync(0,'utf8'));
for(const f of fixtures){const ids=tok.encode(f.text,{add_special_tokens:false}).ids;
if(JSON.stringify(ids)!==JSON.stringify(f.ids)) throw Error('Tokenizer mismatch: '+JSON.stringify({text:f.text,ids,expected:f.ids}));}
console.log('Verified SentencePiece → browser tokenizer parity:',fixtures.length);
"""
    subprocess.run(['node','--input-type=module','-e',script,str(OUTPUT.resolve())],
                   input=json.dumps(fixtures,ensure_ascii=False).encode(),check=True)
    (OUTPUT / 'tokenizer-fixtures.json').write_text(json.dumps(fixtures,ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tokenizer-only', action='store_true', help='Lightweight tokenizer check without audio/model weights.')
    args = parser.parse_args()
    cache = ROOT / 'build/moss-downloads'
    OUTPUT.mkdir(parents=True, exist_ok=True)
    vendor = OUTPUT / 'vendor'
    vendor.mkdir(exist_ok=True)
    archive = download(f'https://registry.npmjs.org/@huggingface/tokenizers/-/tokenizers-{TOKENIZERS_VERSION}.tgz',cache/'tokenizers.tgz')
    with tarfile.open(archive) as tar:
        for source, target in [('package/dist/tokenizers.mjs','tokenizers.mjs'),('package/LICENSE','LICENSE-tokenizers')]:
            (vendor/target).write_bytes(tar.extractfile(source).read())
    model = model_file(TTS_REPO,TTS_REVISION,'tokenizer.model')
    shutil.copyfile(model,OUTPUT/'tokenizer.model')
    prepare_tokenizer(model)
    if args.tokenizer_only:
        return
    from export_stress_dictionary import export_dictionary
    export_dictionary()
    weights={}
    for repo,revision,folder,names in [
        (TTS_REPO,TTS_REVISION,'tts',['tts_browser_onnx_meta.json','moss_tts_prefill.onnx','moss_tts_decode_step.onnx',
                                    'moss_tts_local_fixed_sampled_frame.onnx','moss_tts_global_shared.data','moss_tts_local_shared.data']),
        (CODEC_REPO,CODEC_REVISION,'codec',['codec_browser_onnx_meta.json','moss_audio_tokenizer_decode_full.onnx','moss_audio_tokenizer_decode_shared.data']),
    ]:
        target = OUTPUT / folder
        target.mkdir(exist_ok=True)
        for name in names:
            print('Preparing local MOSS asset:',name,flush=True)
            source=model_file(repo,revision,name)
            if name.endswith('.data'):
                weights[f'{folder}/{name}']=shard_weights(source,target,name)
            else:
                shutil.copyfile(source,target/name)
        shutil.copyfile(model_file(repo,revision,'README.md'),OUTPUT/f'README-{folder}.md')
    (OUTPUT/'weights.json').write_text(json.dumps(weights,indent=2))
    manifest=json.loads(model_file(TTS_REPO,TTS_REVISION,'browser_poc_manifest.json').read_text())
    # No built-in voices or example audios needed: we ship only our fixed prompt.
    for key in ['builtin_voices','text_samples']:
        manifest.pop(key,None)
    (OUTPUT/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False))
    for name in ['LICENSE','ort_cpu_runtime.py']:
        p=download(f'https://raw.githubusercontent.com/OpenMOSS/MOSS-TTS-Nano/{SOURCE_REVISION}/{name}',cache/name)
        shutil.copyfile(p,OUTPUT/('LICENSE-MOSS' if name=='LICENSE' else 'upstream-ort_cpu_runtime.py'))
    for name in ['time-stretch.js','LICENSE']:
        p=download(f'https://raw.githubusercontent.com/Magkino/vocoloco_tts/{VOCO_REVISION}/{name}',cache/f'vocoloco-{name}')
        shutil.copyfile(p,vendor/('time-stretch.js' if name.endswith('.js') else 'LICENSE-time-stretch'))
    # Encode the existing Belarusian voice once on the build machine.
    import numpy as np
    import onnxruntime as ort
    import soundfile as sf
    options=ort.SessionOptions();options.intra_op_num_threads=2
    # ORT validates external-data realpaths: HF blob symlinks are in different
    # directories. Materialize the encoder pair together, outside browser assets.
    encoder_dir=cache/'encoder';encoder_dir.mkdir(exist_ok=True)
    for name in ['moss_audio_tokenizer_encode.onnx','moss_audio_tokenizer_encode.data']:
        shutil.copyfile(model_file(CODEC_REPO,CODEC_REVISION,name),encoder_dir/name)
    encoder=encoder_dir/'moss_audio_tokenizer_encode.onnx'
    ref=ROOT/'framework/belvoice/synth/tts/tts-omnivoice/ref.wav'
    waveform,sr=sf.read(ref,dtype='float32',always_2d=True)
    if sr!=48000:
        import torch,torchaudio
        waveform=torchaudio.functional.resample(torch.from_numpy(waveform.T),sr,48000).numpy().T
    if waveform.shape[1]==1:
        waveform=np.repeat(waveform,2,axis=1)
    waveform=np.ascontiguousarray(waveform.T[None],dtype=np.float32)
    print('Encoding fixed Belarusian MOSS reference:',waveform.shape[-1]/48000,'s',flush=True)
    session=ort.InferenceSession(str(encoder),options,providers=['CPUExecutionProvider'])
    codes,lengths=session.run(['audio_codes','audio_code_lengths'],{'waveform':waveform,'input_lengths':np.array([waveform.shape[-1]],dtype=np.int32)})
    length=int(lengths[0]);codes=codes[0,:length]
    assert codes.shape==(length,16) and np.all((codes>=0)&(codes<1024)),codes.shape
    (OUTPUT/'reference.json').write_text(json.dumps({'codes':codes.astype(int).tolist(),'sampleRate':48000,
        'duration':waveform.shape[-1]/48000,'source':str(ref.relative_to(ROOT)),
        'audioSha256':hashlib.sha256(ref.read_bytes()).hexdigest()},ensure_ascii=False))
    (OUTPUT/'source.json').write_text(json.dumps({'ttsRepo':TTS_REPO,'ttsRevision':TTS_REVISION,
        'codecRepo':CODEC_REPO,'codecRevision':CODEC_REVISION,'sourceRevision':SOURCE_REVISION,
        'tokenizersVersion':TOKENIZERS_VERSION,'timeStretchRevision':VOCO_REVISION,
        'license':'Apache-2.0','browserReaderCodeUsed':False,'runtime':'ONNX Runtime Web 1.31.1'},indent=2))
    print('MOSS assets ready:',OUTPUT,flush=True)


if __name__=='__main__':
    main()
