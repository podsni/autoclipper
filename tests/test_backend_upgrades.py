import asyncio
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from test_backend import load


def seed(m, root, status='completed', job_id='job-one'):
    app = m.create_app(root)
    app.state.store.jobs[job_id] = dict(id=job_id, status=status, stage=status, progress=100 if status in {'completed', 'failed'} else 0, clips=[])
    app.state.store.save()
    return app


def test_delete_outputs_only(tmp_path):
    m = load()
    app = seed(m, tmp_path)
    output = tmp_path/'outputs'/'job-one'
    output.mkdir(parents=True)
    (output/'clip-01.mp4').write_bytes(b'synthetic')
    cache = tmp_path/'cache'/'source.mp4'
    cache.parent.mkdir()
    cache.write_bytes(b'cached')
    secret = tmp_path/'network-password.txt'
    secret.write_text('synthetic-secret')
    with TestClient(app, base_url='http://localhost') as client:
        response = client.delete('/api/jobs/job-one')
        assert response.status_code == 200
        assert response.json() == {'deleted': True, 'id': 'job-one', 'cache_retained': True}
        assert client.get('/api/jobs/job-one').status_code == 404
    assert not output.exists()
    assert cache.read_bytes() == b'cached'
    assert secret.read_text() == 'synthetic-secret'
    assert json.loads((tmp_path/'jobs.json').read_text()) == {}


@pytest.mark.parametrize('status', ['queued', 'downloading', 'transcribing', 'rendering'])
def test_delete_active_missing_and_origin(tmp_path, status):
    m = load()
    app = seed(m, tmp_path)
    with TestClient(app, base_url='http://localhost') as client:
        app.state.store.jobs['job-one']['status'] = status
        assert client.delete('/api/jobs/job-one').status_code == 409
        assert client.delete('/api/jobs/missing').status_code == 404
        assert client.delete('/api/jobs/job-one', headers={'Origin': 'http://evil.test'}).status_code == 403
        assert client.delete('/api/jobs').status_code == 405


@pytest.mark.parametrize('where', ['outputs', 'job', 'child'])
def test_delete_rejects_symlinks(tmp_path, where):
    m = load()
    app = seed(m, tmp_path/'data')
    outside = tmp_path/'outside'
    outside.mkdir()
    (outside/'keep').write_text('safe')
    outputs = app.state.store.root/'outputs'
    if where == 'outputs':
        outputs.symlink_to(outside, target_is_directory=True)
    else:
        outputs.mkdir()
        if where == 'job':
            (outputs/'job-one').symlink_to(outside, target_is_directory=True)
        else:
            (outputs/'job-one').mkdir()
            (outputs/'job-one'/'child').symlink_to(outside, target_is_directory=True)
    with TestClient(app, base_url='http://localhost') as client:
        assert client.delete('/api/jobs/job-one').status_code == 409
    assert (outside/'keep').read_text() == 'safe'


def test_delete_authentication(tmp_path):
    m = load()
    app = m.create_app(tmp_path, allow_network=True, network_password='synthetic-password')
    with TestClient(app, base_url='http://192.168.1.10', client=('192.168.1.20', 1234)) as client:
        app.state.store.jobs['job-one'] = dict(id='job-one', status='failed', clips=[])
        assert client.delete('/api/jobs/job-one').status_code == 401
        assert client.delete('/api/jobs/job-one', auth=('autoclipper', 'synthetic-password')).status_code == 200


def test_delete_save_failure_rolls_back(tmp_path, monkeypatch):
    m = load()
    app = seed(m, tmp_path)
    output = tmp_path/'outputs'/'job-one'
    output.mkdir(parents=True)
    (output/'clip.mp4').write_bytes(b'synthetic')
    with TestClient(app, base_url='http://localhost') as client:
        def fail():
            raise OSError('synthetic write failure')
        monkeypatch.setattr(app.state.store, 'save', fail)
        assert client.delete('/api/jobs/job-one').status_code == 500
        assert client.get('/api/jobs/job-one').status_code == 200
        assert (output/'clip.mp4').read_bytes() == b'synthetic'


def test_sse_initial_final_payload_and_missing(tmp_path):
    m = load()
    app = seed(m, tmp_path)
    with TestClient(app, base_url='http://localhost') as client:
        assert client.get('/api/jobs/missing/events').status_code == 404
        response = client.get('/api/jobs/job-one/events')
        assert response.status_code == 200
        assert response.headers['content-type'].startswith('text/event-stream')
        assert response.text.startswith('event: job\ndata: ')
        assert json.loads(response.text.split('data: ', 1)[1]) == app.state.store.jobs['job-one']


def test_sse_changes_heartbeat_disconnect(tmp_path):
    m = load()
    app = seed(m, tmp_path, status='rendering')
    store = app.state.store
    class Request:
        disconnected = False
        async def is_disconnected(self):
            return self.disconnected
    async def check():
        request = Request()
        stream = m.job_events(store, 'job-one', request, interval=.001, heartbeat=.001)
        assert '"status": "rendering"' in await anext(stream)
        assert await anext(stream) == ': heartbeat\n\n'
        m.update(store, 'job-one', progress=75)
        assert '"progress": 75' in await anext(stream)
        request.disconnected = True
        with pytest.raises(StopAsyncIteration):
            await anext(stream)
        request.disconnected = False
        stream = m.job_events(store, 'job-one', request, interval=.001)
        await anext(stream)
        m.update(store, 'job-one', status='completed')
        assert '"status": "completed"' in await anext(stream)
        with pytest.raises(StopAsyncIteration):
            await anext(stream)
    asyncio.run(check())


def test_render_clip_reports_real_monotonic_ffmpeg_progress(tmp_path, synthetic_local_demo):
    m = load()
    output = tmp_path/'render'
    output.mkdir()
    observed = []
    store = seed(m, tmp_path/'live-store', status='rendering').state.store
    class Request:
        async def is_disconnected(self):
            return False
    snapshots = []
    def report(value):
        observed.append(value)
        m.update(store, 'job-one', progress=40+50*value)
        async def snapshot():
            stream = m.job_events(store, 'job-one', Request())
            payload = await anext(stream)
            await stream.aclose()
            return json.loads(payload.split('data: ', 1)[1])
        snapshots.append(asyncio.run(snapshot()))
    result = m.render_clip(synthetic_local_demo/'source.mp4', [{'text': 'synthetic', 'start': 0, 'end': 1}], {'start': 0, 'end': 1.4}, output, 'crop', 'clip-01', progress_callback=report)
    assert any(0 <= value < 1 for value in observed)
    assert all(record['status'] == 'rendering' for record in snapshots)
    assert [record['progress'] for record in snapshots] == [40+50*value for value in observed]
    assert result['checks'] == {'video': True, 'audio': True, 'vertical': True}
    assert observed and observed[-1] == 1
    assert observed == sorted(observed)
    assert all(0 <= value <= 1 for value in observed)


def test_pipeline_weights_actual_clip_durations_and_labels_unknown(tmp_path, monkeypatch):
    m = load()
    store = m.Store(tmp_path)
    store.jobs['unit'] = dict(id='unit', url='https://youtu.be/abcdefghijk', title='Synthetic', clip_count=2, layout='crop', clips=[], progress=0)
    transcript = tmp_path/'transcript.json'
    transcript.write_text(json.dumps({'words': [{'text':'synthetic', 'start':0, 'end':1}]}))
    monkeypatch.setattr(m, 'cached_inputs', lambda *_: (tmp_path/'source.mp4', transcript, {}))
    monkeypatch.setattr(m, 'probe', lambda *_: {'format': {'duration':100}})
    monkeypatch.setattr(m, 'select_candidates', lambda *_: [{'start':0, 'end':10}, {'start':10, 'end':40}])
    records = []
    original = m.update
    def capture(store, job_id, **changes):
        original(store, job_id, **changes)
        records.append(json.loads(json.dumps(store.jobs[job_id])))
    monkeypatch.setattr(m, 'update', capture)
    def render(*args, **kwargs):
        callback = kwargs.get('progress_callback')
        assert callable(callback), 'Pipeline must connect live encoder progress to Store'
        for fraction in (0, .5, .25, 1):
            callback(fraction)
        return {'id':args[5]}
    monkeypatch.setattr(m, 'render_clip', render)
    monkeypatch.setattr(m, 'finish_archive', lambda *_: None)
    m.process_job(store, 'unit')
    assert records[0]['progress_detail']['indeterminate'] is True
    rendering = [r for r in records if r.get('progress_detail', {}).get('source') == 'ffmpeg']
    assert rendering
    assert any(r['progress'] == pytest.approx(46.25) for r in rendering)
    assert any(r['progress'] == pytest.approx(71.25) for r in rendering)
    assert [r['progress'] for r in records] == sorted(r['progress'] for r in records)
    assert all(r['progress_detail']['total_clips'] == 2 for r in rendering)
    assert all(r['progress_label'] == 'Weighted pipeline progress' for r in records)


def test_queued_job_has_progress_contract(tmp_path):
    from test_contract import payload
    m = load()
    with TestClient(m.create_app(tmp_path, processor=lambda *_: None), base_url='http://localhost') as client:
        item = client.post('/api/jobs', json=payload()).json()
        assert item['progress_label'] == 'Weighted pipeline progress'
        assert item['progress_detail'] == {'stage_progress': None, 'current_clip': None, 'total_clips': 0, 'indeterminate': True, 'source': 'queued'}


def test_delete_cleanup_failure_keeps_hidden_quarantine(tmp_path, monkeypatch):
    m = load()
    app = seed(m, tmp_path)
    output = tmp_path/'outputs'/'job-one'
    output.mkdir(parents=True)
    (output/'clip.mp4').write_bytes(b'synthetic')
    with TestClient(app, base_url='http://localhost') as client:
        def fail(*_):
            raise OSError('synthetic cleanup failure')
        monkeypatch.setattr(m.shutil, 'rmtree', fail)
        result = client.delete('/api/jobs/job-one')
        assert result.status_code == 200
        assert result.json()['cleanup_pending'] is True
        assert client.get('/api/jobs/job-one').status_code == 404
        assert client.get('/api/jobs/job-one/files/clip.mp4').status_code == 404
        assert not output.exists()
        assert len(list((tmp_path/'outputs').glob('.deleted-*'))) == 1


def test_render_parser_bounds_and_timeout(tmp_path):
    import sys
    import subprocess
    m = load()
    observed = []
    script = "import time; print('out_time_us=N/A\\nout_time_ms=nan\\nout_time_us=-1\\nout_time_ms=500000', flush=True); time.sleep(.25); print('out_time_us=250000\\nout_time_us=9999999999', flush=True)"
    m.render_command([sys.executable, '-c', script], 1, observed.append, timeout=5)
    assert observed == sorted(observed)
    assert observed[0] == .5 and observed[-1] == 1
    with pytest.raises(subprocess.TimeoutExpired):
        m.render_command([sys.executable, '-c', 'import time; time.sleep(10)'], 1, None, timeout=.1)
