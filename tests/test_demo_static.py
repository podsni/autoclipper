import json
import subprocess
from fastapi.testclient import TestClient
from test_backend import load


def test_static_index_and_allowlisted_assets_only(tmp_path):
    m=load()
    static=tmp_path/'static'; static.mkdir()
    (static/'index.html').write_text('<h1>Real UI</h1>')
    (static/'app.js').write_text('console.log("local")')
    (static/'.env').write_text('PRIVATE')
    with TestClient(m.create_app(tmp_path/'data',static_dir=static),base_url='http://localhost') as c:
        assert '<h1>Real UI</h1>' in c.get('/').text
        assert c.get('/static/app.js').status_code==200
        assert c.get('/static/.env').status_code==404
        assert c.get('/app.py').status_code==404
        assert c.get('/static/%2e%2e/app.py').status_code==404


def test_explicit_demo_import_is_synthetic_media_idempotent_and_not_automatic(tmp_path,monkeypatch,synthetic_local_demo):
    m=load()
    monkeypatch.setattr(m,'EXISTING',synthetic_local_demo)
    store=m.Store(tmp_path)
    assert store.jobs=={}
    item=m.import_existing_demo(store)
    assert item['status']=='completed'
    assert item['clips'][0]['selection_method']=='manual'
    assert 'existing' in item['message'].lower()
    assert item['clips'][0]['start']==0
    assert all(item['clips'][0]['checks'].values())
    assert len(m.Store(tmp_path).jobs)==1
    assert m.import_existing_demo(store)['id']==item['id']
    assert len(store.jobs)==1
    with TestClient(m.create_app(tmp_path),base_url='http://localhost') as c:
        assert c.get(item['clips'][0]['video_url'],headers={'range':'bytes=0-31'}).status_code==206
        assert c.get(item['zip_url']).status_code==200


def test_cli_refuses_public_binding():
    m=load()
    result=subprocess.run([str(m.ROOT/'.venv/bin/python'),str(m.ROOT/'app.py'),'--host','0.0.0.0'],capture_output=True,text=True,timeout=10)
    assert result.returncode != 0
    assert 'requires --allow-network' in result.stderr
