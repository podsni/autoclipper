import socket
import subprocess
import pytest
import json
import shutil


@pytest.fixture
def synthetic_local_demo(tmp_path):
    """Generated test-pattern/sine fixture, never real user media or STT."""
    folder=tmp_path/'synthetic-demo';folder.mkdir()
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','color=black:size=720x1280:rate=15','-f','lavfi','-i','sine=frequency=440','-t','1.5','-c:v','libx264','-threads','2','-c:a','aac',str(folder/'shorts-ai-bubble-final.mp4')],check=True)
    shutil.copy2(folder/'shorts-ai-bubble-final.mp4',folder/'source.mp4')
    (folder/'shorts-captions.srt').write_text('1\n00:00:00,000 --> 00:00:01,400\nSYNTHETIC FIXTURE\n')
    (folder/'edit-plan.json').write_text(json.dumps({'source_start_seconds':0,'source_end_seconds':1.4}))
    (folder/'transcript.json').write_text(json.dumps({'words':[{'text':'fixture','start':i*.01,'end':i*.01+.009} for i in range(120)]}))
    return folder


@pytest.fixture(autouse=True)
def no_paid_api_or_external_network(monkeypatch):
    """Tests must never contact YouTube/Deepgram, even after a regression."""
    monkeypatch.delenv('DEEPGRAM_API_KEY',raising=False)
    original_run=subprocess.run
    def offline_run(args,*a,**kw):
        text=' '.join(str(x) for x in args) if isinstance(args,(list,tuple)) else str(args)
        if 'yt_dlp' in text or 'deepgram_transcribe.py' in text or '--allow-paid-api' in text:
            raise AssertionError('Real paid/download subprocess forbidden in tests')
        return original_run(args,*a,**kw)
    monkeypatch.setattr(subprocess,'run',offline_run)
    original_connect=socket.socket.connect
    def offline_connect(sock,address):
        if sock.family in (socket.AF_INET,socket.AF_INET6):
            raise AssertionError('External sockets forbidden in tests')
        return original_connect(sock,address)
    monkeypatch.setattr(socket.socket,'connect',offline_connect)
