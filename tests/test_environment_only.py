import json
import subprocess
from pathlib import Path
from test_backend import load
from test_inputs import make_store


def test_local_transcription_needs_no_api_key_or_dotenv(tmp_path, monkeypatch):
    m=load();monkeypatch.setattr(m,'PROFILE',tmp_path)
    # A stray Deepgram key in the environment must be ignored: transcription
    # is local now, so no key or .env file is ever consulted.
    monkeypatch.setenv('DEEPGRAM_API_KEY','synthetic-environment-key')
    commands=[];cache=tmp_path/'cache'/'abcdefghijk'
    def fake(args,timeout=0,cwd=None):
        args=[str(x) for x in args];commands.append(args)
        if '--dump-single-json' in args:
            return subprocess.CompletedProcess(args,0,json.dumps({'id':'abcdefghijk','duration':40,'title':'Fixture','is_live':False}).encode(),b'')
        if 'yt_dlp' in args:(cache/'source.mp4').write_bytes(b'SYNTHETIC: probe is stubbed')
        if 'whisper_transcribe.py' in ' '.join(args):
            assert '--env-file' not in args
            assert '--allow-paid-api' not in args
            prefix=Path(args[args.index('--output-prefix')+1])
            prefix.with_suffix('.json').write_text(json.dumps({'words':[{'text':'fixture','start':0,'end':1}]}))
        return subprocess.CompletedProcess(args,0,b'',b'')
    monkeypatch.setattr(m,'command',fake)
    monkeypatch.setattr(m,'probe',lambda _: {'format':{'duration':'40'}})
    assert m.transcription_configured()
    m.cached_inputs(make_store(m,tmp_path,'abcdefghijk'),'unit')
    assert len(commands)==3
