import json
import subprocess
import zipfile
import pytest
from fastapi.testclient import TestClient
from test_backend import load
from test_contract import payload


def test_srt_cannot_overlap_or_emit_zero_duration(tmp_path):
    m=load()
    path=tmp_path/'test.srt'
    words=[dict(text='End.',start=0,end=1),dict(text='Next.',start=.6,end=1.2),dict(text='tiny',start=1.201,end=1.2011)]
    m.write_subtitles(words,0,1.2011,path)
    times=[line for line in path.read_text().splitlines() if '-->' in line]
    def ms(value):
        h,mi,s=value.replace(',', '.').split(':');return int(h)*3600+int(mi)*60+float(s)
    pairs=[tuple(ms(v) for v in line.split(' --> ')) for line in times]
    assert len(pairs)>=2 and all(a<b for a,b in pairs)
    assert all(a[1]<=b[0] for a,b in zip(pairs,pairs[1:]))


def test_long_cues_never_exceed_two_lines_and_interpolated_words_do_not_highlight(tmp_path):
    m=load()
    words=[dict(text='abcdefghijklm',start=i*.2,end=i*.2+.15,timing_source='interpolated') for i in range(8)]
    path=tmp_path/'test.ass'
    m.write_ass(words,0,2,path,'highlight')
    events=[line.split(',',9)[9] for line in path.read_text().splitlines() if line.startswith('Dialogue:')]
    assert events and all(text.count(r'\N')<=1 for text in events)
    assert all(r'{\c' not in text for text in events)
    interpolated=m.normalize_words({'segments':[{'start':0,'end':2,'text':'two words'}]})
    assert all(w.get('timing_source')=='interpolated' for w in interpolated)


def test_ass_cues_are_clipped_nonoverlapping_and_pause_aware(tmp_path):
    m = load()
    assert hasattr(m, 'write_ass'), 'ASS writer missing'
    words = [dict(text=t, start=a, end=b) for t,a,b in [
        ('Hello.', 0, .7), ('actual', .6, 1.1), ('words', 1.1, 1.4),
        ('pause', 2, 2.5), ('{\\\\pos(1,1)}safe', 2.5, 3.2), ('tiny', 3.201, 3.202)]]
    for style in ('clean', 'highlight'):
        path = tmp_path / (style+'.ass')
        m.write_ass(words, .2, 3.202, path, style)
        text = path.read_text()
        assert 'PlayResX: 720' in text and 'PlayResY: 1280' in text
        assert 'DejaVu Sans,40' in text and ',220,' in text
        events = [line.split(',', 9) for line in text.splitlines() if line.startswith('Dialogue:')]
        assert events and len({tuple(e) for e in events}) == len(events)
        def seconds(value):
            h,mi,s = value.split(':'); return int(h)*3600+int(mi)*60+float(s)
        times = [(seconds(e[1]), seconds(e[2])) for e in events]
        assert all(0 <= a < b <= 3 for a,b in times)
        assert all(a[1] <= b[0] for a,b in zip(times,times[1:]))
        assert all(e[9].count(r'\N') <= 1 for e in events)
        assert '\\\\pos' not in text
        assert events[0][9].endswith('Hello.') if style == 'clean' else '&H0000FFFF&' in text


@pytest.mark.parametrize('style,layout', [('clean','fit'),('highlight','crop')])
def test_real_ass_burn_and_optional_download(tmp_path, style, layout):
    m = load()
    source = tmp_path/'source.mp4'
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','color=black:size=320x180:rate=15','-f','lavfi','-i','sine=frequency=440','-t','1.5','-c:v','libx264','-threads','2','-c:a','aac',str(source)],check=True)
    output=tmp_path/'outputs'/'fixture'; output.mkdir(parents=True)
    words=[dict(text='Actual',start=0,end=.6),dict(text='words.',start=.65,end=1.3)]
    result=m.render_clip(source,words,dict(start=0,end=1.4,title='Actual words',caption='Actual words.'),output,layout,'clip-01',subtitle_style=style)
    assert result['checks']['vertical']
    assert (output/'clip-01.ass').is_file()
    pixels=subprocess.run(['ffmpeg','-v','error','-ss','0.3','-i',str(output/'clip-01.mp4'),'-frames:v','1','-f','rawvideo','-pix_fmt','rgb24','-'],capture_output=True,check=True).stdout
    bright=[]; yellow=0
    for y in range(1280):
        for x in range(720):
            r,g,b=pixels[(y*720+x)*3:(y*720+x)*3+3]
            if r>180 and g>180: bright.append(y)
            if r>180 and g>180 and b<100: yellow+=1
    assert bright and 920<=min(bright)<=1060 and max(bright)<1070
    assert (yellow>50) == (style=='highlight')
    clip=dict(result, video_url='/clip-01.mp4',subtitle_url='/clip-01.srt',poster_url='/clip-01.jpg',ass_url='/clip-01.ass')
    with TestClient(m.create_app(tmp_path),base_url='http://localhost') as c:
        store=c.app.state.store
        store.jobs['fixture']=dict(id='fixture',status='rendering',clips=[clip])
        m.finish_archive(store,'fixture')
        assert c.get('/api/jobs/fixture/files/clip-01.ass').status_code==200
        assert c.get('/api/jobs/fixture/files/other.ass').status_code==404
        with zipfile.ZipFile(output/'download.zip') as z:
            assert 'clip-01.ass' in z.namelist()


@pytest.mark.parametrize('platform', ['Shorts','TikTok'])
@pytest.mark.parametrize('style', ['singkat','informatif','pertanyaan'])
def test_local_caption_endpoint_is_grounded_and_legacy_compatible(tmp_path, platform, style):
    m=load()
    with TestClient(m.create_app(tmp_path),base_url='http://localhost') as c:
        c.app.state.store.jobs['old']=dict(id='old',status='completed',channel='Fixture channel',url='https://www.youtube.com/watch?v=HU4I_W7qtMc',clips=[dict(id='clip-01',title='Teknologi data',caption='Teknologi data membantu analisis. '+('Lanjutan. '*100))])
        before=json.dumps(c.app.state.store.jobs)
        r=c.post('/api/jobs/old/clips/clip-01/caption',json=dict(platform=platform,style=style,provider='local-template'))
        assert r.status_code==200
        data=r.json()
        assert data['method']=='local-template' and data['platform']==platform and data['style']==style
        assert 'Teknologi data' in data['text'] and 'CTA umum:' in data['text']
        assert 'Fixture channel' in data['text'] and '#Teknologi' in data['text']
        assert len(data['text'])<1000 and 'bukan AI' in data['disclaimer']
        assert before==json.dumps(c.app.state.store.jobs), 'Caption drafts must not mutate production jobs'
        assert c.post('/api/jobs/old/clips/missing/caption',json=dict(platform=platform,style=style)).status_code==404
        assert c.post('/api/jobs/missing/clips/x/caption',json=dict(platform=platform,style=style)).status_code==404
        assert c.post('/api/jobs/old/clips/clip-01/caption',json=dict(platform='bad',style=style)).status_code==422


def test_gemini_backend_uses_exact_model_and_never_falls_back(tmp_path, monkeypatch):
    import httpx
    import captions
    m=load()
    monkeypatch.setenv('GEMINI_API_KEY','synthetic-test-key')
    captured=[]
    def post(url, **kwargs):
        captured.append((url,kwargs))
        return httpx.Response(200,json={'status':'completed','steps':[{'type':'model_output','content':[{'type':'text','text':'{"text":"Draf dari transkrip.","title":"Data"}'}]}]})
    monkeypatch.setattr(httpx,'post',post)
    with TestClient(m.create_app(tmp_path),base_url='http://localhost') as c:
        c.app.state.store.jobs['fixture']=dict(id='fixture',status='completed',channel='Fixture',clips=[dict(id='clip-01',title='Data',caption='Data nyata.')])
        url='/api/jobs/fixture/clips/clip-01/caption'
        response=c.post(url,json=dict(platform='Shorts',style='singkat',provider='gemini'))
        assert response.status_code==200 and response.json()['method']=='gemini'
        endpoint,kw=captured[0]
        assert endpoint=='https://generativelanguage.googleapis.com/v1beta/interactions'
        assert kw['headers']['x-goog-api-key']=='synthetic-test-key'
        body=kw['json']
        assert body['model']=='models/gemini-3.8-flash' and body['store'] is False
        assert body['generation_config']['max_output_tokens']==2048
        assert 'tools' not in body and 'Data nyata.' in body['input']
        assert 0<kw['timeout']<=120
        def overloaded(*a,**k): return httpx.Response(503,json={'error':{'message':'do not expose provider body'}})
        monkeypatch.setattr(httpx,'post',overloaded)
        failure=c.post(url,json=dict(platform='TikTok',style='singkat',provider='gemini'))
        assert failure.status_code==503 and 'Gemini' in failure.json()['detail']
        assert 'do not expose' not in failure.text and 'local-template' not in failure.text
        def timeout(*a,**k): raise httpx.ReadTimeout('secret provider context')
        monkeypatch.setattr(httpx,'post',timeout)
        failure=c.post(url,json=dict(platform='TikTok',style='singkat',provider='gemini'))
        assert failure.status_code==504 and 'secret' not in failure.text


def test_groq_default_sends_source_context_and_actual_response(tmp_path, monkeypatch):
    import httpx
    import captions
    m=load()
    monkeypatch.setenv('GROQ_API_KEY','synthetic-groq-key')
    captured=[]
    def post(url,**kwargs):
        captured.append((url,kwargs))
        return httpx.Response(200,json={'choices':[{'message':{'content':'{"text":"Draf satir, bukan rekomendasi.","title":"Kritik aplikasi"}'}}]})
    monkeypatch.setattr(httpx,'post',post)
    with TestClient(m.create_app(tmp_path),base_url='http://localhost') as c:
        c.app.state.store.jobs['fixture']=dict(id='fixture',status='completed',title='Satire Directapp',channel='Eno Bening',clips=[dict(id='clip-01',title='Aplikasi',caption='Katanya aplikasi baru, padahal sama saja.')])
        response=c.post('/api/jobs/fixture/clips/clip-01/caption',json=dict(platform='TikTok',style='singkat'))
        assert response.status_code==200 and response.json()['method']=='groq'
        endpoint,kw=captured[0]
        assert endpoint=='https://api.groq.com/openai/v1/chat/completions'
        assert kw['headers']['Authorization']=='Bearer synthetic-groq-key'
        assert kw['json']['model']=='openai/gpt-oss-20b'
        assert kw['json']['max_completion_tokens']==1536
        content=json.dumps(kw['json']['messages'],ensure_ascii=False)
        assert 'Satire Directapp' in content and 'Eno Bening' in content and 'sarkasme' in content


def test_subtitle_style_contract(tmp_path):
    m = load()
    with TestClient(m.create_app(tmp_path, processor=lambda *_: None), base_url='http://localhost') as c:
        assert c.post('/api/jobs', json=payload()).json().get('subtitle_style') == 'clean'
        assert c.post('/api/jobs', json=dict(payload(), subtitle_style='highlight')).status_code == 202
        assert c.post('/api/jobs', json=dict(payload(), subtitle_style='invalid')).status_code == 422
