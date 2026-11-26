from test_backend import load
from fastapi.testclient import TestClient


def payload(**changes):
    return dict(url='https://www.youtube.com/watch?v=HU4I_W7qtMc', clip_count=1,
                language='id', layout='fit', rights_confirmed=True, **changes)


def test_create_validation_local_security_and_restart(tmp_path):
    m = load()
    # No real pipeline/network in this contract test.
    def pause(store, job_id):
        pass
    with TestClient(m.create_app(tmp_path, processor=pause), base_url='http://localhost') as c:
        for field, value in [('rights_confirmed', False), ('clip_count', 9), ('clip_count', 0), ('language', 'xx'), ('layout', 'other'), ('url', 'https://evil.test/watch?v=HU4I_W7qtMc'), ('url', 'https://youtu.be/HU4I_W7qtMcX'), ('url', 'https://youtube.com/playlist?list=x'), ('url', 'https://youtube.com/watch?v=HU4I_W7qtMc&list=x')]:
            body = payload(); body[field] = value
            assert c.post('/api/jobs', json=body).status_code == 422, (field, value)
        assert c.post('/api/jobs', json=payload(), headers={'origin':'https://evil.test'}).status_code == 403
        assert c.get('/api/health', headers={'host':'evil.test'}).status_code == 403
        assert c.post('/api/jobs', content='{}', headers={'content-type':'text/plain'}).status_code == 415
        assert c.post('/api/jobs', json=payload(), headers={'sec-fetch-site':'cross-site'}).status_code == 403
        response = c.post('/api/jobs', json=payload(), headers={'origin':'http://localhost'})
        assert response.status_code == 202
        job = response.json()
        assert job['status'] == 'queued' and job['clips'] == []
        assert job['progress'] == 0 and job['id'] and job['created_at']
        assert c.get('/api/jobs/' + job['id']).json()['url'] == payload()['url']
    with TestClient(m.create_app(tmp_path, processor=pause), base_url='http://localhost') as c:
        restored = c.get('/api/jobs').json()['jobs'][0]
        assert restored['status'] == 'failed'
        assert 'interrupted' in restored['error'].lower()


def test_youtube_ids_are_strict_and_not_repaired():
    m = load()
    for url in ['https://youtu.be/HU4I_W7qtMc', 'https://youtube.com/shorts/HU4I_W7qtMc', 'https://m.youtube.com/watch?v=HU4I_W7qtMc']:
        assert m.youtube_id(url) == 'HU4I_W7qtMc'
    import pytest
    for url in ['http://youtu.be/HU4I_W7qtMc', 'https://user@youtube.com/watch?v=HU4I_W7qtMc', 'https://youtube.com:443/watch?v=HU4I_W7qtMc', 'https://youtu.be/%48U4I_W7qtMc', 'https://youtu.be/HU4I_W7qtM', 'https://youtu.be/HU4I_W7qtMc/extra']:
        with pytest.raises(ValueError): m.youtube_id(url)
