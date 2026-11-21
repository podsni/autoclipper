import json
from pathlib import Path
import subprocess
import pytest
from test_backend import load
from test_contract import payload


def make_store(m, root, video='HU4I_W7qtMc'):
    store=m.Store(root)
    store.jobs['unit']=dict(id='unit',stage='downloading',status='downloading',url='https://youtu.be/'+video,language='id')
    return store


def test_authorized_existing_cache_uses_synthetic_files_without_network(tmp_path,monkeypatch, synthetic_local_demo):
    m=load()
    monkeypatch.setattr(m,'EXISTING',synthetic_local_demo)
    def forbidden(*args,**kwargs): raise AssertionError('Network subprocess is forbidden')
    monkeypatch.setattr(m,'command',forbidden)
    source,transcript,metadata=m.cached_inputs(make_store(m,tmp_path),'unit')
    assert source == m.EXISTING/'source.mp4'
    assert transcript == m.EXISTING/'transcript.json'
    assert len(m.normalize_words(json.loads(transcript.read_text())))>100


@pytest.mark.parametrize('env_file', [True, False])
def test_uncached_download_and_transcription_commands_are_bounded_and_reused(tmp_path,monkeypatch,env_file):
    m=load()
    profile=tmp_path/'synthetic-profile'
    profile.mkdir()
    monkeypatch.setattr(m,'PROFILE',profile)
    monkeypatch.setenv('DEEPGRAM_API_KEY','synthetic-not-a-real-key')
    if env_file:
        (profile/'.env').write_text('DEEPGRAM_API_KEY=synthetic-not-a-real-key\n')
    calls=[]
    cache=tmp_path/'cache'/'abcdefghijk'
    def fake_command(args,timeout=0,cwd=None):
        args=[str(a) for a in args]; calls.append((args,timeout))
        if '--dump-single-json' in args:
            return subprocess.CompletedProcess(args,0,json.dumps({'id':'abcdefghijk','duration':40,'title':'Actual metadata','channel':'Actual channel','is_live':False}).encode(),b'')
        if 'yt_dlp' in args:
            (cache/'source.mp4').write_bytes(b'synthetic placeholder: probe stubbed, not media evidence')
        if 'deepgram_transcribe.py' in ' '.join(args):
            detail = store.jobs['unit']['progress_detail']
            assert detail['stage_progress'] is None and detail['indeterminate'] is True
            assert detail['source'] == 'transcribing'
            prefix=Path(args[args.index('--output-prefix')+1])
            prefix.with_suffix('.json').write_text(json.dumps({'words':[{'text':'fixture','start':0,'end':1}]}))
        return subprocess.CompletedProcess(args,0,b'',b'')
    monkeypatch.setattr(m,'command',fake_command)
    monkeypatch.setattr(m,'probe',lambda p:{'format':{'duration':'40'}})
    store=make_store(m,tmp_path,'abcdefghijk')
    source,transcript,metadata=m.cached_inputs(store,'unit')
    assert source.is_file() and transcript.is_file() and metadata['title']=='Actual metadata'
    assert len(calls)==3
    download=calls[1][0]; transcribe=calls[2][0]
    assert '--no-playlist' in download and '--ignore-config' in download
    assert '--remote-components' in download and 'ejs:github' in download
    assert '--allow-paid-api' in transcribe
    assert ('--env-file' in transcribe) is env_file
    assert (str(m.PROFILE/'.env') in transcribe) is env_file
    assert all(0<t<=1800 for _,t in calls)
    m.cached_inputs(store,'unit')
    assert len(calls)==3


def test_overlong_or_live_source_rejected_before_download_and_paid_api(tmp_path,monkeypatch):
    m=load()
    for metadata in [{'id':'abcdefghijk','duration':3601}, {'id':'abcdefghijk','duration':10,'is_live':True}]:
        calls=[]
        def fake(args,**kwargs):
            calls.append(args)
            return subprocess.CompletedProcess(args,0,json.dumps(metadata).encode(),b'')
        monkeypatch.setattr(m,'command',fake)
        with pytest.raises(ValueError): m.cached_inputs(make_store(m,tmp_path,'abcdefghijk'),'unit')
        assert len(calls)==1
