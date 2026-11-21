import io
import json
import subprocess
import time
import zipfile
from fastapi.testclient import TestClient
from test_backend import load
from test_contract import payload


def test_offline_synthetic_ffmpeg_job_range_zip_and_traversal(tmp_path):
    m = load()
    cache = tmp_path / 'cache' / 'HU4I_W7qtMc'
    cache.mkdir(parents=True)
    # Clearly synthetic video/audio, NOT a real STT result.
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','testsrc2=size=320x180:rate=15','-f','lavfi','-i','sine=frequency=440:sample_rate=44100','-t','5','-c:v','libx264','-threads','2','-c:a','aac',str(cache/'source.mp4')],check=True)
    (cache/'transcript.json').write_text(json.dumps({'words':[{'text':f'Synthetic{i}.','start':i*.4,'end':i*.4+.3} for i in range(12)]}))
    (cache/'metadata.json').write_text(json.dumps({'title':'Synthetic offline fixture', 'channel':'Test fixture'}))
    with TestClient(m.create_app(tmp_path),base_url='http://localhost') as c:
        created = c.post('/api/jobs',json=payload()).json()
        deadline = time.monotonic()+90
        while time.monotonic() < deadline:
            job = c.get('/api/jobs/'+created['id']).json()
            if job['status'] in {'completed','failed'}: break
            time.sleep(.1)
        assert job['status'] == 'completed', job
        assert job['progress'] == 100 and job['title'] == 'Synthetic offline fixture'
        clip = job['clips'][0]
        assert clip['checks'] == {'video':True,'audio':True,'vertical':True}
        assert clip['selection_method'] == 'heuristic'
        video = c.get(clip['video_url'],headers={'range':'bytes=0-99'})
        assert video.status_code == 206 and len(video.content) == 100
        assert video.headers['content-range'].startswith('bytes 0-99/')
        assert 'Synthetic' in c.get(clip['subtitle_url']).text
        assert c.get(clip['poster_url']).headers['content-type'] == 'image/jpeg'
        # Caption pixels belong in the lower safe area, not over the full-width
        # foreground. Read a raw RGB frame; no image-analysis dependency needed.
        video_path=tmp_path/'outputs'/job['id']/'clip-01.mp4'
        pixels=subprocess.run(['ffmpeg','-v','error','-ss','0.2','-i',str(video_path),'-frames:v','1','-f','rawvideo','-pix_fmt','rgb24','-'],capture_output=True,check=True).stdout
        bottom=pixels[1050*720*3:1240*720*3]
        white=sum(min(bottom[i:i+3])>230 for i in range(0,len(bottom),3))
        assert white>100, 'Burned captions must be readable in lower safe area'
        archive = c.get(job['zip_url'])
        assert archive.headers['content-type'] == 'application/zip'
        with zipfile.ZipFile(io.BytesIO(archive.content)) as z:
            assert set(z.namelist()) == {'clip-01.mp4','clip-01.srt','clip-01.jpg','clip-01.ass','manifest.json'}
        assert c.get(f'/api/jobs/{job["id"]}/files/source.mp4').status_code == 404
        assert c.get(f'/api/jobs/{job["id"]}/files/%2e%2e%2fjobs.json').status_code == 404
        assert c.get('/.env').status_code == 404
        source = cache/'source.mp4'
        assert source.exists()
    # Crop is a distinct actual encoder path, also checked by full decode.
    out = tmp_path/'crop'; out.mkdir()
    words = m.normalize_words(json.loads((cache/'transcript.json').read_text()))
    result = m.render_clip(source, words, dict(start=0,end=2,title='Synthetic',caption='Synthetic',selection_method='heuristic'), out, 'crop', 'clip-01')
    assert result['checks']['vertical']


def test_pipeline_failure_is_safe_and_durable(tmp_path):
    m = load()
    def broken(store, job_id):
        raise RuntimeError('secret must not reach API')
    with TestClient(m.create_app(tmp_path, processor=broken),base_url='http://localhost') as c:
        job_id = c.post('/api/jobs',json=payload()).json()['id']
        deadline=time.monotonic()+5
        while time.monotonic()<deadline:
            result = c.get('/api/jobs/'+job_id).json()
            if result['status']=='failed': break
            time.sleep(.02)
        assert result['status']=='failed'
        assert 'secret' not in json.dumps(result)
