import threading
import time
import pytest
from fastapi.testclient import TestClient
from test_backend import load
from test_contract import payload


def test_strict_urls_reject_stripped_controls():
    m=load()
    for url in [' https://youtu.be/HU4I_W7qtMc','https://youtu.be/HU4I_\nW7qtMc','https://youtube.com/watch?v=HU4I_\tW7qtMc']:
        with pytest.raises(ValueError): m.youtube_id(url)


def test_single_worker_serializes_jobs(tmp_path):
    m=load()
    active=0; maximum=0; sequence=[]
    guard=threading.Lock()
    def work(store,job_id):
        nonlocal active,maximum
        with guard:
            active+=1; maximum=max(maximum,active)
        time.sleep(.08)
        m.update(store,job_id,status='completed',stage='completed',progress=100)
        with guard:
            active-=1; sequence.append(job_id)
    with TestClient(m.create_app(tmp_path,processor=work),base_url='http://localhost') as c:
        ids=[c.post('/api/jobs',json=payload()).json()['id'] for _ in range(3)]
    assert maximum==1 and sequence==ids


def test_cached_overlong_source_is_rejected_before_paid_transcription(tmp_path,monkeypatch):
    m=load()
    from test_inputs import make_store
    cache=tmp_path/'cache'/'abcdefghijk'; cache.mkdir(parents=True)
    (cache/'source.mp4').write_bytes(b'placeholder, probe is stubbed')
    monkeypatch.setattr(m,'probe',lambda p:{'format':{'duration':'3601'}})
    with pytest.raises(ValueError): m.cached_inputs(make_store(m,tmp_path,'abcdefghijk'),'unit')


def test_download_enables_available_node_runtime(tmp_path,monkeypatch):
    m=load()
    from test_inputs import make_store
    import subprocess,json
    seen=[]
    def reject_large(args,**kwargs):
        seen.extend(str(a) for a in args)
        return subprocess.CompletedProcess(args,0,json.dumps({'id':'abcdefghijk','duration':4000}).encode(),b'')
    monkeypatch.setattr(m,'command',reject_large)
    with pytest.raises(ValueError): m.cached_inputs(make_store(m,tmp_path,'abcdefghijk'),'unit')
    assert '--js-runtimes' in seen and 'node' in seen
