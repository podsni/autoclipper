"""Local-only AutoClipper backend. No network work happens at import."""
import json
import os
import sys
import threading
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
import subprocess
import shutil
import zipfile
from pydantic import BaseModel, Field, field_validator, ConfigDict, StrictBool
from typing import Literal
from urllib.parse import urlsplit, parse_qs
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import uuid
import re
from subtitles import write_ass
from captions import CaptionRequest, local_caption, ai_caption


def youtube_id(url):
    if any(ord(char) <= 32 or ord(char) == 127 for char in url):
        raise ValueError('Whitespace/control characters in URLs are not supported')
    p = urlsplit(url)
    if p.scheme != 'https' or p.netloc not in {'youtube.com', 'www.youtube.com', 'm.youtube.com', 'youtu.be'} or p.fragment:
        raise ValueError('Use a single HTTPS YouTube video URL')
    q = parse_qs(p.query, keep_blank_values=True)
    if 'list' in q or 'index' in q:
        raise ValueError('Playlists are not supported')
    if p.netloc == 'youtu.be':
        token = p.path[1:]
    elif p.path == '/watch' and len(q.get('v', [])) == 1:
        token = q['v'][0]
        # Encoded IDs are not repaired by query parsing.
        if '%' in p.query:
            raise ValueError('Encoded identifiers are not supported')
    elif p.path.startswith(('/shorts/', '/embed/')):
        token = p.path.split('/', 2)[2]
    else:
        raise ValueError('Use a YouTube video URL')
    if not re.fullmatch(r'[A-Za-z0-9_-]{11}', token):
        raise ValueError('YouTube video ID must contain exactly 11 allowed characters')
    return token


class JobRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    url: str = Field(max_length=2048)
    clip_count: int = Field(ge=1, le=8, strict=True)
    language: Literal['id', 'en']
    layout: Literal['fit', 'crop']
    subtitle_style: Literal['clean', 'highlight'] = 'clean'
    render_preset: Literal['standard', 'reference'] = 'standard'
    headline: str = Field(default='', max_length=120)
    rights_confirmed: StrictBool
    paid_confirmed: StrictBool

    @field_validator('url')
    @classmethod
    def valid_url(cls, value):
        youtube_id(value)
        return value

    @field_validator('rights_confirmed', 'paid_confirmed')
    @classmethod
    def consent(cls, value):
        if not value:
            raise ValueError('Explicit rights and paid-API consent are required')
        return value

ROOT = Path(__file__).resolve().parent
PROFILE = ROOT
EXISTING = ROOT / 'examples' / 'local-demo'
CLIPPER = ROOT / 'vendor' / 'youtube-clipper'


def deepgram_configured():
    if os.environ.get('DEEPGRAM_API_KEY'):
        return True
    env = PROFILE / '.env'
    if not env.is_file():
        return False
    return any(line.strip().startswith('DEEPGRAM_API_KEY=') and bool(line.split('=', 1)[1].strip().strip('\"\'')) for line in env.read_text().splitlines())


class Store:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.path = self.root / 'jobs.json'
        self.jobs = json.loads(self.path.read_text()) if self.path.exists() else {}

    def save(self):
        with self.lock:
            temporary = self.path.with_suffix('.tmp')
            temporary.write_text(json.dumps(self.jobs, ensure_ascii=False, indent=2))
            temporary.replace(self.path)


def create_app(data_dir=None, processor=None, static_dir=None, *, allow_network=False, network_password=None, network_username='autoclipper', allow_weak_password=False):
    minimum = 6 if allow_weak_password else 16
    if allow_network and (not network_password or len(network_password) < minimum):
        raise ValueError(f'Network mode requires a password of at least {minimum} characters')
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', network_username):
        raise ValueError('Invalid network username')
    store = Store(data_dir or ROOT / 'data')
    static_root = Path(static_dir or ROOT / 'static')

    @asynccontextmanager
    async def lifespan(app):
        for item in store.jobs.values():
            if item['status'] not in {'completed', 'failed'}:
                item.update(status='failed', stage='failed', error='Job interrupted by server restart', message='Job interrupted; cached source and transcript are retained.')
        store.save()
        app.state.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='clipper')
        yield
        app.state.executor.shutdown(wait=True, cancel_futures=False)

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.store = store

    @app.middleware('http')
    async def local_only(request: Request, call_next):
        import ipaddress
        import base64
        import secrets

        def permitted_origin(value):
            try:
                p = urlsplit(value)
                if p.scheme != 'http' or p.username is not None or p.password is not None or p.path or p.query or p.fragment:
                    return False
                if p.hostname in {'localhost', '127.0.0.1', '::1'}:
                    return True
                if not allow_network:
                    return False
                address = ipaddress.ip_address(p.hostname)
                return not address.is_unspecified and not address.is_multicast
            except (ValueError, TypeError):
                return False
        origin = request.headers.get('origin')
        host_origin = 'http://' + request.headers.get('host', '')
        if not permitted_origin(host_origin) or (origin and origin != host_origin) or request.headers.get('sec-fetch-site') == 'cross-site':
            return JSONResponse({'detail':'Same-origin access through localhost or an IP address required'}, status_code=403)
        try:
            local_client = ipaddress.ip_address(request.client.host).is_loopback
        except (ValueError, AttributeError):
            local_client = False
        if allow_network and not local_client:
            authenticated = False
            header = request.headers.get('authorization', '')
            try:
                scheme, encoded = header.split(' ', 1)
                if scheme.lower() == 'basic' and len(encoded) < 2048:
                    username, password = base64.b64decode(encoded, validate=True).decode('utf-8').split(':', 1)
                    authenticated = secrets.compare_digest(username.encode(), network_username.encode()) and secrets.compare_digest(password.encode(), network_password.encode())
            except (ValueError, UnicodeError):
                pass
            if not authenticated:
                return JSONResponse({'detail':'Authentication required'}, status_code=401, headers={'WWW-Authenticate':'Basic realm="AutoClipper", charset="UTF-8"', 'Cache-Control':'no-store'})
        if request.method == 'POST' and request.headers.get('content-type', '').split(';')[0].strip() != 'application/json':
            return JSONResponse({'detail':'JSON required'}, status_code=415)
        response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; media-src 'self' blob:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'"
        return response

    @app.post('/api/jobs', status_code=202)
    def create_job(body: JobRequest):
        job_id = uuid.uuid4().hex
        item = dict(id=job_id, url=body.url, title='YouTube ' + youtube_id(body.url), channel='', status='queued', progress=0, stage='queued', message='Queued for local processing', created_at=datetime.now(timezone.utc).isoformat(), clips=[], **body.model_dump(exclude={'url'}))
        with store.lock:
            store.jobs[job_id] = item
            store.save()
            snapshot = dict(item)
        app.state.executor.submit(run_safely, processor or process_job, store, job_id)
        return snapshot

    @app.get('/api/health')
    def health():
        return {'status': 'ok', 'deepgram_configured': deepgram_configured()}

    @app.get('/api/jobs')
    def jobs():
        return {'jobs': list(reversed(list(store.jobs.values())))}

    @app.get('/api/jobs/{job_id}')
    def job(job_id: str):
        if job_id not in store.jobs:
            raise HTTPException(404, 'Job not found')
        return store.jobs[job_id]

    @app.post('/api/jobs/{job_id}/clips/{clip_id}/caption')
    def caption(job_id: str, clip_id: str, body: CaptionRequest):
        with store.lock:
            item = job(job_id)
            clip = next((dict(c) for c in item.get('clips', []) if c.get('id') == clip_id), None)
            source = {k: item.get(k, '') for k in ('title', 'channel', 'url')}
        if clip is None:
            raise HTTPException(404, 'Clip not found')
        try:
            if body.provider != 'local-template':
                return ai_caption(clip, source, body.platform, body.style, PROFILE / '.env', body.provider)
            return local_caption(clip, source, body.platform, body.style)
        except ValueError as error:
            raise HTTPException(422, str(error)) from None

    @app.get('/api/jobs/{job_id}/files/{filename}')
    def job_file(job_id: str, filename: str):
        item = job(job_id)
        allowed = {Path(clip[field]).name for clip in item['clips'] for field in ('video_url', 'subtitle_url', 'poster_url', 'ass_url') if clip.get(field)}
        if filename not in allowed or not re.fullmatch(r'[A-Za-z0-9_-]+\.(mp4|srt|jpg|ass)', filename):
            raise HTTPException(404, 'File not found')
        path = store.root / 'outputs' / job_id / filename
        if path.is_symlink() or not path.is_file():
            raise HTTPException(404, 'File not found')
        return FileResponse(path, media_type={'.mp4':'video/mp4','.srt':'application/x-subrip','.jpg':'image/jpeg','.ass':'text/plain'}[path.suffix])

    @app.get('/api/jobs/{job_id}/download.zip')
    def download_zip(job_id: str):
        item = job(job_id)
        path = store.root / 'outputs' / job_id / 'download.zip'
        if item['status'] != 'completed' or not path.is_file() or path.is_symlink():
            raise HTTPException(404, 'Archive not ready')
        return FileResponse(path, media_type='application/zip', filename='autoclipper-' + job_id[:8] + '.zip')

    @app.get('/')
    def index():
        path = static_root/'index.html'
        if not path.is_file() or path.is_symlink():
            raise HTTPException(404, 'Frontend not installed')
        return FileResponse(path, media_type='text/html')

    @app.get('/static/{filename}')
    def static_asset(filename: str):
        if filename not in {'app.js','styles.css'}:
            raise HTTPException(404, 'Asset not found')
        path=static_root/filename
        if not path.is_file() or path.is_symlink():
            raise HTTPException(404, 'Asset not found')
        return FileResponse(path,media_type='text/javascript' if filename.endswith('.js') else 'text/css')

    return app


def update(store, job_id, **changes):
    with store.lock:
        store.jobs[job_id].update(changes)
        store.save()


def run_safely(processor, store, job_id):
    try:
        processor(store, job_id)
    except Exception:
        # Never expose subprocess/provider error bodies, credentials, or local paths.
        current = store.jobs[job_id]['stage']
        message = 'Processing failed during ' + current + '. Cached inputs are retained; check local dependencies, source availability, or API configuration.'
        update(store, job_id, status='failed', stage='failed', error=message, message=message)


def command(args, timeout=600, cwd=None):
    return subprocess.run([str(a) for a in args], cwd=cwd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)


def probe(path):
    return json.loads(command(['ffprobe','-v','error','-show_streams','-show_format','-of','json',path],timeout=30).stdout)


def verify_media(path):
    data = probe(path)
    video = next((s for s in data['streams'] if s['codec_type']=='video'), {})
    audio = next((s for s in data['streams'] if s['codec_type']=='audio'), {})
    checks = dict(video=video.get('codec_name')=='h264', audio=audio.get('codec_name')=='aac', vertical=(video.get('width'),video.get('height'))==(720,1280))
    if not all(checks.values()):
        raise ValueError('Rendered media failed stream checks')
    command(['ffmpeg','-v','error','-xerror','-i',path,'-map','0:v:0','-map','0:a:0','-f','null','-'], timeout=600)
    return checks, float(data['format']['duration'])


def render_clip(source, words, candidate, output, layout, clip_id, subtitle_style='clean', render_preset='standard', headline='', source_credit=''):
    output = Path(output)
    srt = output / (clip_id+'.srt')
    video = output / (clip_id+'.mp4')
    poster = output / (clip_id+'.jpg')
    write_subtitles(words,candidate['start'],candidate['end'],srt)
    ass = output / (clip_id+'.ass')
    write_ass(words,candidate['start'],candidate['end'],ass,subtitle_style,render_preset=render_preset,headline=headline or candidate.get('title',''),credit=source_credit)
    if render_preset == 'reference':
        graph = '[0:v]split=2[bg][fg];[bg]scale=180:320:force_original_aspect_ratio=increase,crop=180:320,boxblur=8:2,eq=brightness=-0.40:saturation=0.65,scale=720:1280[blur];[fg]scale=720:520:force_original_aspect_ratio=decrease[front];[blur][front]overlay=(W-w)/2:340'
    elif layout == 'fit':
        graph = '[0:v]split=2[bg][fg];[bg]scale=180:320:force_original_aspect_ratio=increase,crop=180:320,boxblur=8:2,eq=brightness=-0.18,scale=720:1280[blur];[fg]scale=720:1280:force_original_aspect_ratio=decrease[front];[blur][front]overlay=(W-w)/2:(H-h)/2'
    else:
        graph = '[0:v]scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280'
    # Only app-generated filenames, never a user-supplied filter/path.
    graph += f",setsar=1,ass={ass.name}[v]"
    command(['ffmpeg','-v','error','-n','-filter_complex_threads','2','-ss',candidate['start'],'-i',Path(source).resolve(),'-t',candidate['end']-candidate['start'],'-filter_complex',graph,'-map','[v]','-map','0:a:0','-c:v','libx264','-preset','veryfast','-crf','23','-threads','2','-pix_fmt','yuv420p','-r','30','-c:a','aac','-b:a','128k','-movflags','+faststart',video.name],cwd=output,timeout=900)
    checks, duration = verify_media(video)
    command(['ffmpeg','-v','error','-n','-ss',min(1,duration/2),'-i',video,'-frames:v','1','-threads','2',poster],timeout=30)
    return dict(candidate, id=clip_id, duration=duration, checks=checks)


def cached_inputs(store, job_id):
    item = store.jobs[job_id]
    video_id = youtube_id(item['url'])
    cache = store.root / 'cache' / video_id
    cache.mkdir(parents=True, exist_ok=True)
    source, transcript = cache/'source.mp4', cache/'transcript.json'
    # Reuse this one explicitly authorized source by exact validated ID only.
    # Existing files are read, never moved, deleted, or rewritten.
    if video_id == 'HU4I_W7qtMc':
        if not source.is_file() and (EXISTING/'source.mp4').is_file():
            source = EXISTING/'source.mp4'
        if not transcript.is_file() and (EXISTING/'transcript.json').is_file():
            transcript = EXISTING/'transcript.json'
    metadata_path=cache/'metadata.json'
    metadata=json.loads(metadata_path.read_text()) if metadata_path.exists() else {}
    if not source.is_file():
        python=Path(sys.executable)
        canonical='https://www.youtube.com/watch?v='+video_id
        base=[python,'-m','yt_dlp','--ignore-config','--no-playlist','--no-warnings','--no-progress','--socket-timeout','15','--retries','0','--extractor-retries','0','--remote-components','ejs:github','--js-runtimes','node']
        info=json.loads(command(base+['--dump-single-json','--skip-download',canonical],timeout=120).stdout)
        duration=info.get('duration')
        if info.get('id') != video_id or info.get('_type','video') != 'video' or info.get('is_live') or not isinstance(duration,(int,float)) or not 0 < duration <= 3600:
            raise ValueError('Only non-live videos of at most one hour are supported')
        metadata={'title':str(info.get('title') or ('YouTube '+video_id))[:500], 'channel':str(info.get('channel') or info.get('uploader') or '')[:200]}
        metadata_path.write_text(json.dumps(metadata,ensure_ascii=False))
        command(base+['--match-filter','duration <= 3600 & !is_live','--max-filesize','2G','-f','bv*[height<=1080]+ba/b[height<=1080]','--merge-output-format','mp4','--remux-video','mp4','-o',str(cache/'source.%(ext)s'),canonical],timeout=1800)
    if not transcript.is_file():
        duration=float(probe(source)['format']['duration'])
        if not 0 < duration <= 3600:
            raise ValueError('Source duration exceeds one hour')
        update(store,job_id,status='transcribing',stage='transcribing',progress=20,message='Sending source audio to Deepgram with explicit paid-API consent; no automatic paid retry')
        prefix=cache/('transcription-'+uuid.uuid4().hex)
        transcription_command=[Path(sys.executable),CLIPPER/'scripts/deepgram_transcribe.py',source,'--language',item['language'],'--allow-paid-api','--output-prefix',prefix]
        if (PROFILE/'.env').is_file():
            transcription_command += ['--env-file',PROFILE/'.env']
        command(transcription_command,timeout=1800)
        produced=prefix.with_suffix('.json')
        normalize_words(json.loads(produced.read_text()))
        produced.replace(transcript)
    return source, transcript, metadata


def finish_archive(store, job_id):
    item = store.jobs[job_id]
    output = store.root/'outputs'/job_id
    manifest = dict(item)
    manifest.update(status='completed',stage='completed',progress=100)
    (output/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
    with zipfile.ZipFile(output/'download.zip','w',compression=zipfile.ZIP_DEFLATED) as archive:
        for clip in item['clips']:
            for ext in ('mp4','srt','jpg'):
                path=output/(clip['id']+'.'+ext)
                archive.write(path,path.name)
            ass=output/(clip['id']+'.ass')
            if clip.get('ass_url') and ass.is_file() and not ass.is_symlink():
                archive.write(ass,ass.name)
        archive.write(output/'manifest.json','manifest.json')
    update(store,job_id,status='completed',stage='completed',progress=100,message=f"{len(item['clips'])} clip(s) rendered and decoded. Selection is heuristic, not AI fact-checking or a virality score.",zip_url=f'/api/jobs/{job_id}/download.zip')


def process_job(store, job_id):
    item = store.jobs[job_id]
    update(store,job_id,status='downloading',stage='downloading',progress=5,message='Checking validated video cache')
    source, transcript, metadata = cached_inputs(store,job_id)
    duration=float(probe(source)['format']['duration'])
    if not 0 < duration <= 3600:
        raise ValueError('Source duration exceeds one hour')
    update(store,job_id,title=metadata.get('title') or item['title'],channel=metadata.get('channel') or '',status='transcribing',stage='transcribing',progress=25,message='Reusing cached transcript; no paid API call')
    words=normalize_words(json.loads(transcript.read_text()))
    update(store,job_id,status='selecting',stage='selecting',progress=35,message='Selecting nonoverlapping speech windows using sentence/topic-cue heuristics only')
    candidates=select_candidates(words,duration,item['clip_count'])
    output=store.root/'outputs'/job_id
    output.mkdir(parents=True,exist_ok=True)
    for i,candidate in enumerate(candidates,1):
        update(store,job_id,status='rendering',stage='rendering',progress=40+int((i-1)/len(candidates)*50),message=f'Rendering and decoding clip {i}/{len(candidates)}')
        clip_id=f'clip-{i:02d}'
        clip=render_clip(source,words,candidate,output,item['layout'],clip_id,subtitle_style=item.get('subtitle_style','clean'),render_preset=item.get('render_preset','standard'),headline=item.get('headline',''),source_credit='Sumber: '+(item.get('channel') or item.get('title','Video asal')))
        clip['render_preset']=item.get('render_preset','standard')
        clip['ass_url']=f'/api/jobs/{job_id}/files/{clip_id}.ass'
        for field,ext in [('video_url','mp4'),('subtitle_url','srt'),('poster_url','jpg')]:
            clip[field]=f'/api/jobs/{job_id}/files/{clip_id}.{ext}'
        with store.lock:
            item['clips'].append(clip)
            store.save()
    finish_archive(store,job_id)


def normalize_words(data):
    """Validate normalized/Deepgram words; segment-only timing is interpolated."""
    import math
    raw = data.get('words')
    if raw is None and 'results' in data:
        raw = data['results']['channels'][0]['alternatives'][0].get('words')
    if raw is None:
        raw = []
        for segment in data.get('segments', []):
            tokens = segment['text'].split()
            start, end = float(segment['start']), float(segment['end'])
            if not tokens or not math.isfinite(start) or not math.isfinite(end) or start < 0 or end <= start:
                raise ValueError('Invalid transcript segment')
            for i, token in enumerate(tokens):
                raw.append({'text':token, 'start':start+(end-start)*i/len(tokens), 'end':start+(end-start)*(i+1)/len(tokens), 'timing_source':'interpolated'})
    words = []
    previous = -1
    for item in raw:
        text = item.get('punctuated_word') or item.get('text') or item.get('word') or ''
        start, end = float(item['start']), float(item['end'])
        if not text.strip() or not math.isfinite(start) or not math.isfinite(end) or start < 0 or end <= start or start < previous:
            raise ValueError('Invalid transcript word timing')
        word = {'text':text.strip(), 'start':start, 'end':end}
        if item.get('timing_source') == 'interpolated':
            word['timing_source'] = 'interpolated'
        words.append(word)
        previous = start
    if not words:
        raise ValueError('No timed speech in transcript')
    return words


def select_candidates(words, duration, count):
    """Sentence/topic-cue heuristics only. No semantic or virality claims."""
    words = [w for w in words if w['start'] < duration]
    if not words:
        raise ValueError('No speech within source duration')
    candidates = []
    starts = [0] + [i for i in range(1, len(words)) if words[i-1]['text'].endswith(('.', '?', '!')) or words[i]['start']-words[i-1]['end'] > 1.2]
    # Word windows are a fallback for unpunctuated speech.
    if len(starts) < count + 1:
        starts = sorted(set(starts + list(range(0, len(words), 10))))
    cues = {'ai','teknologi','technology','bubble','inovasi','innovation','model','data'}
    for first in starts:
        start = words[first]['start']
        possible = [(i,w) for i,w in enumerate(words[first:], first) if 30 <= min(w['end'],duration)-start <= 60]
        if not possible:
            continue
        last, final = min(possible, key=lambda pair: (0 if pair[1]['text'].endswith(('.', '?', '!')) else 20) + abs(pair[1]['end']-start-45))
        excerpt = words[first:last+1]
        text = ' '.join(w['text'] for w in excerpt)
        tokens=[w['text'].lower().strip('.,!?') for w in excerpt]
        score = sum(token in cues for token in tokens) / max(1,len(excerpt))
        # Personnel/drama topic cues are downranked, not fact-checked.
        personnel={'dipecat','dikeluarkan','fired','jensen','jenson','huang','ceo','skandal','scandal','penipuan'}
        score -= .12*sum(token in personnel for token in tokens)
        score += .2 if final['text'].endswith(('.', '?', '!')) else 0
        candidates.append((score, start, min(final['end'],duration), text))
    selected = []
    for score,start,end,text in sorted(candidates, key=lambda c:(-c[0], c[1])):
        if all(end <= c['start'] or start >= c['end'] for c in selected):
            selected.append(dict(start=start,end=end,title=' '.join(text.split()[:10]),caption=text,selection_method='heuristic'))
        if len(selected) >= count:
            break
    if not selected:
        end = min(duration, words[-1]['end'], words[0]['start']+60)
        text = ' '.join(w['text'] for w in words if w['start'] < end)
        selected = [dict(start=words[0]['start'],end=end,title=' '.join(text.split()[:10]),caption=text,selection_method='heuristic')]
    return sorted(selected,key=lambda c:c['start'])


def write_subtitles(words, start, end, path):
    import html
    def timestamp(value):
        ms = max(0, round(value*1000))
        return f'{ms//3600000:02}:{ms//60000%60:02}:{ms//1000%60:02},{ms%1000:03}'
    visible = [w for w in words if w['start'] < end and w['end'] > start]
    groups = []
    group = []
    for word in visible:
        if group and (len(group) == 5 or word['start']-group[-1]['end'] > .4 or group[-1]['text'].endswith(('.', '?', '!', ';', ':'))):
            groups.append(group); group=[]
        group.append(word)
    if group: groups.append(group)
    lines = []
    import math
    cursor = 0
    for group in groups:
        a = max(cursor, 0, math.ceil((group[0]['start']-start)*1000-1e-7))
        b = min(math.floor((end-start)*1000+1e-7), math.floor((group[-1]['end']-start)*1000+1e-7))
        if a >= b:
            continue
        text = html.escape(' '.join(w['text'].replace('\\','').replace('{','').replace('}','').replace('\n',' ').replace('\r',' ') for w in group))
        lines.append(f'{len(lines)+1}\n{timestamp(a/1000)} --> {timestamp(b/1000)}\n{text}\n')
        cursor = b
    Path(path).write_text('\n'.join(lines), encoding='utf-8')


def import_existing_demo(store):
    """Explicit CLI-only import, from fixed previously authorized paths."""
    job_id='demo-HU4I_W7qtMc'
    if job_id in store.jobs and store.jobs[job_id]['status']=='completed':
        return store.jobs[job_id]
    source=EXISTING/'shorts-ai-bubble-final.mp4'
    subtitles=EXISTING/'shorts-captions.srt'
    plan=json.loads((EXISTING/'edit-plan.json').read_text())
    checks,duration=verify_media(source)
    output=store.root/'outputs'/job_id
    output.mkdir(parents=True,exist_ok=True)
    shutil.copy2(source,output/'clip-01.mp4')
    shutil.copy2(subtitles,output/'clip-01.srt')
    command(['ffmpeg','-v','error','-y','-ss','1','-i',source,'-frames:v','1','-threads','2',output/'clip-01.jpg'],timeout=30)
    words=normalize_words(json.loads((EXISTING/'transcript.json').read_text()))
    caption=' '.join(w['text'] for w in words if w['start'] >= plan['source_start_seconds'] and w['start'] < plan['source_end_seconds'])
    clip=dict(id='clip-01',title=' '.join(caption.split()[:10]),start=plan['source_start_seconds'],end=plan['source_end_seconds'],duration=duration,selection_method='manual',caption=caption,checks=checks)
    for field,ext in [('video_url','mp4'),('subtitle_url','srt'),('poster_url','jpg')]:
        clip[field]=f'/api/jobs/{job_id}/files/clip-01.{ext}'
    store.jobs[job_id]=dict(id=job_id,url='https://www.youtube.com/watch?v=HU4I_W7qtMc',title='Existing result · AI bubble',channel='Raymond Chin',status='rendering',progress=95,stage='rendering',message='Importing actual previously rendered result',created_at=datetime.now(timezone.utc).isoformat(),clips=[clip],example=True)
    finish_archive(store,job_id)
    update(store,job_id,message='Actual existing result imported explicitly: manual selection, previously rendered MP4 and edited SRT; verified by ffprobe and full decode. Not a new automatic selection or paid transcription.')
    return store.jobs[job_id]


app = create_app()


if __name__ == '__main__':
    import argparse
    import uvicorn
    parser=argparse.ArgumentParser(description='AutoClipper studio; explicit authenticated network mode available')
    parser.add_argument('--host',default='127.0.0.1',choices=['127.0.0.1','localhost','::1','0.0.0.0','::'])
    parser.add_argument('--port',type=int,default=8787)
    parser.add_argument('--allow-network',action='store_true',help='Enable IP-address access with mandatory login for remote clients')
    parser.add_argument('--username',default='autoclipper',help='Network login username')
    parser.add_argument('--allow-weak-password',action='store_true',help='Explicitly accept user-chosen password with minimum 6 characters; trusted networks only')
    parser.add_argument('--password-file',type=Path,default=ROOT/'data'/'network-password.txt',help='Private password file; generated if absent, never printed')
    parser.add_argument('--import-existing-demo',action='store_true',help='Explicitly import previously rendered authorized result, then start local server')
    options=parser.parse_args()
    if not 1 <= options.port <= 65535:
        parser.error('Port must be in 1..65535')
    if options.host in {'0.0.0.0','::'} and not options.allow_network:
        parser.error('Non-loopback binding requires --allow-network')
    if options.allow_network:
        import secrets
        password_path=options.password_file
        if password_path.is_symlink():
            parser.error('Password file must not be a symlink')
        password_path.parent.mkdir(parents=True,exist_ok=True)
        if not password_path.exists():
            fd=os.open(password_path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            with os.fdopen(fd,'w') as stream:
                stream.write(secrets.token_urlsafe(24)+'\n')
        os.chmod(password_path,0o600)
        password=password_path.read_text().strip()
        minimum=6 if options.allow_weak_password else 16
        if len(password)<minimum:
            parser.error(f'Password file must contain at least {minimum} characters')
        app=create_app(allow_network=True,network_password=password,network_username=options.username,allow_weak_password=options.allow_weak_password)
    if options.import_existing_demo:
        import_existing_demo(app.state.store)
    uvicorn.run(app,host=options.host,port=options.port,workers=1,proxy_headers=False)
