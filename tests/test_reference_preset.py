import subprocess
from fastapi.testclient import TestClient
from test_backend import load
from test_contract import payload


def test_editorial_preset_contract_backwards_compatible(tmp_path):
    m=load()
    with TestClient(m.create_app(tmp_path,processor=lambda *_:None),base_url='http://localhost') as c:
        assert c.post('/api/jobs',json=payload()).json()['render_preset']=='standard'
        response=c.post('/api/jobs',json=dict(payload(),render_preset='reference',headline='Aplikasi DM terpisah?'))
        assert response.status_code==202
        assert response.json()['headline']=='Aplikasi DM terpisah?'
        assert c.post('/api/jobs',json=dict(payload(),render_preset='bad')).status_code==422


def test_reference_ass_has_single_header_credit_and_bounded_text(tmp_path):
    m=load();out=tmp_path/'captions.ass'
    m.write_ass([dict(text='Uji.',start=0,end=1)],0,1.5,out,'clean',headline='Judul {\\pos(1,1)} aman\n'+'panjang '*80,credit='Sumber: Nama {\\move} pengguna',render_preset='reference')
    data=out.read_text()
    events=[line.split(',',9) for line in data.splitlines() if line.startswith('Dialogue:')]
    titles=[e for e in events if e[3]=='Title'];credits=[e for e in events if e[3]=='Credit']
    assert len(titles)==len(credits)==1
    assert titles[0][9].count(r'\N')<=1
    assert r'\pos' not in titles[0][9] and r'\move' not in credits[0][9]
    assert '&H0000E5FF' in data


def test_reference_render_has_top_title_safe_subtitle_credit(tmp_path):
    m=load();source=tmp_path/'source.mp4';out=tmp_path/'render';out.mkdir()
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','color=black:size=320x180:rate=15','-f','lavfi','-i','sine=frequency=440','-t','1.5','-c:v','libx264','-threads','2','-c:a','aac',str(source)],check=True)
    result=m.render_clip(source,[dict(text='Subtitle nyata.',start=0,end=1.3)],dict(start=0,end=1.4,title='Judul nyata',caption='Subtitle nyata.'),out,'fit','clip-01',render_preset='reference',headline='JUDUL KUNING',source_credit='Sumber: Uji')
    assert result['checks']['vertical']
    pixels=subprocess.run(['ffmpeg','-v','error','-ss','0.4','-i',str(out/'clip-01.mp4'),'-frames:v','1','-f','rawvideo','-pix_fmt','rgb24','-'],capture_output=True,check=True).stdout
    def count(y0,y1,yellow=False):
        n=0
        for y in range(y0,y1):
            for x in range(720):
                r,g,b=pixels[(y*720+x)*3:(y*720+x)*3+3]
                n+= r>160 and g>140 and (b<120 if yellow else b>140)
        return n
    assert count(100,270,True)>100
    assert count(880,1040)>100
    assert count(1040,1140)>30
