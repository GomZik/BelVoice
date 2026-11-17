"""Compare browser MOSS traces against the original Apache-2.0 Python runtime.

Loads native CPU sessions sequentially, with identical sampling uniforms.
No dependency or model downloads; needs prepare_moss.py and a browser --trace.
"""
import argparse
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import time

import numpy as np
import onnxruntime as ort
import sentencepiece as spm
import soundfile as sf

ROOT=Path(__file__).resolve().parents[2]
ASSETS=ROOT/'browser_demo/moss'


class BrowserRandom:
    def __init__(self):
        self.state=42

    def random(self):
        self.state=(self.state*1664525+1013904223)&0xffffffff
        return min(.99999994,self.state/4294967296)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--browser',type=Path,required=True,help='Directory containing trace.json and report.json')
    parser.add_argument('--output',type=Path,default=Path('/tmp/opencode/belvoice-moss-native'))
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    trace=json.loads((args.browser/'trace.json').read_text())
    report=json.loads((args.browser/'report.json').read_text())['result']
    model_dir=args.output/'models';model_dir.mkdir(exist_ok=True)
    weights=json.loads((ASSETS/'weights.json').read_text())
    for name,weight in weights.items():
        target=model_dir/Path(name).name
        if not target.exists() or target.stat().st_size!=weight['bytes']:
            with target.open('wb') as out:
                for part in weight['parts']:
                    with (ASSETS/Path(name).parent/part['path']).open('rb') as source:
                        shutil.copyfileobj(source,out)
    spec=importlib.util.spec_from_file_location('moss_upstream_reference',ASSETS/'upstream-ort_cpu_runtime.py')
    upstream=importlib.util.module_from_spec(spec);sys.modules[spec.name]=upstream;spec.loader.exec_module(upstream)
    runtime=upstream.OrtCpuRuntime.__new__(upstream.OrtCpuRuntime)
    runtime.manifest=json.loads((ASSETS/'manifest.json').read_text())
    runtime.tts_meta=json.loads((ASSETS/'tts/tts_browser_onnx_meta.json').read_text())
    runtime.rng=BrowserRandom()
    runtime.sessions={}
    runtime.manifest['generation_defaults']['max_new_frames']=100
    tokenizer=spm.SentencePieceProcessor(model_file=str(ASSETS/'tokenizer.model'))
    text_ids=tokenizer.encode(report['normalized'])
    assert trace['textIds']==text_ids,'Text tokenizer mismatch'
    codes=json.loads((ASSETS/'reference.json').read_text())['codes']
    request=runtime.build_voice_clone_request_rows(codes,text_ids)
    assert request['inputIds']==trace['rows'],'Prompt layout mismatch'
    print('Verified original SentencePiece IDs and complete original prompt layout.',flush=True)
    options=ort.SessionOptions();options.intra_op_num_threads=4
    for key,folder,name in [('prefill','tts','moss_tts_prefill.onnx'),('decode','tts','moss_tts_decode_step.onnx'),
                            ('local_fixed_sampled_frame','tts','moss_tts_local_fixed_sampled_frame.onnx'),
                            ('codec_decode','codec','moss_audio_tokenizer_decode_full.onnx')]:
        target=model_dir/name;shutil.copyfile(ASSETS/folder/name,target)
        print('Loading native reference:',key,flush=True)
        runtime.sessions[key]=ort.InferenceSession(str(target),options,providers=['CPUExecutionProvider'])
    started=time.monotonic()
    frames=runtime.generate_audio_frames(request)
    browser_frames=trace['frames']
    prefix=0
    for a,b in zip(frames,browser_frames):
        if a!=b:
            break
        prefix+=1
    channels,length=runtime.decode_full_audio(frames)
    stereo=np.stack(channels,axis=-1)
    sf.write(args.output/'native-stereo.wav',stereo,48000,subtype='PCM_16')
    mono=stereo.mean(axis=1)
    sf.write(args.output/'native.wav',mono,48000,subtype='PCM_16')
    result={'browserFrames':len(browser_frames),'nativeFrames':len(frames),'identicalFramePrefix':prefix,
            'allFramesIdentical':frames==browser_frames,'duration':length/48000,'nativeSynthesisSeconds':time.monotonic()-started}
    (args.output/'report.json').write_text(json.dumps(result,indent=2))
    (args.output/'frames.json').write_text(json.dumps(frames))
    print('Native comparison:',json.dumps(result),flush=True)


if __name__=='__main__':
    main()
