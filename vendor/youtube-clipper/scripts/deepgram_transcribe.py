#!/usr/bin/env python3
"""Deepgram-only transcription and portable timed subtitle utilities."""


import argparse
import http.client
import json
import math
import os
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urlencode


def run_ffmpeg(arguments, *, cwd=None):
    try:
        result = subprocess.run(['ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'error',
                                 '-n', *map(str, arguments)], cwd=cwd,
                                capture_output=True, text=True)
    except OSError:
        raise RuntimeError('FFmpeg unavailable') from None
    if result.returncode:
        raise RuntimeError('FFmpeg failed; check media streams, codecs and filters')


def extract_audio(source, output):
    source, output = Path(source).resolve(), Path(output)
    guard_outputs([output], [source])
    output.parent.mkdir(parents=True, exist_ok=True)
    run_ffmpeg(['-i', source, '-map', '0:a:0', '-vn', '-ac', '1', '-ar', '16000',
                '-c:a', 'pcm_s16le', output])
    return output


def read_key(env_file=None):
    from dotenv import dotenv_values
    if env_file is not None and not Path(env_file).is_file():
        raise ValueError('--env-file does not exist or is not a file')
    values = dotenv_values(env_file) if env_file is not None else {}
    key = os.environ.get('DEEPGRAM_API_KEY') or values.get('DEEPGRAM_API_KEY')
    if not key or not key.strip():
        raise ValueError('Set DEEPGRAM_API_KEY in environment or explicit --env-file')
    if not key.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) > 126 for c in key):
        raise ValueError('Invalid DEEPGRAM_API_KEY format')
    return key


def transcribe(audio, *, allow_paid_api=False, language='en', model='nova-3', env_file=None):
    if not allow_paid_api:
        raise ValueError('Network transcription requires --allow-paid-api')
    key = read_key(env_file)
    audio = Path(audio)
    query = urlencode({'model': model, 'language': language, 'punctuate': 'true',
                       'smart_format': 'true'})
    connection = http.client.HTTPSConnection('api.deepgram.com', timeout=300)
    try:
        with audio.open('rb') as stream:
            connection.request('POST', '/v1/listen?' + query, body=stream, headers={
                'Authorization': 'Token ' + key, 'Content-Type': 'audio/wav',
                'Content-Length': str(audio.stat().st_size)})
            result = connection.getresponse()
            if result.status != 200:
                raise RuntimeError(f'Deepgram HTTP {result.status}; no automatic paid retry')
            payload = json.loads(result.read())
    except (OSError, http.client.HTTPException, ValueError):
        raise RuntimeError('Deepgram transport/JSON failure; no automatic paid retry') from None
    finally:
        connection.close()
    return normalize(payload)


def normalize(payload):
    try:
        words = payload['results']['channels'][0]['alternatives'][0]['words']
        if not isinstance(words, list) or not words:
            raise ValueError('No timed words in transcript')
        previous = 0.0
        for word in words:
            if (isinstance(word['start'], bool) or isinstance(word['end'], bool)
                    or not isinstance(word.get('punctuated_word', word['word']), str)):
                raise ValueError('Invalid word timestamp or text types')
            text = word.get('punctuated_word', word['word'])
            if not text.strip() or '\n' in text or '\r' in text or '-->' in text:
                raise ValueError('Word text cannot form a valid subtitle cue')
            start, end = float(word['start']), float(word['end'])
            if (not math.isfinite(start) or not math.isfinite(end)
                    or start < previous or end <= start
                    or not isinstance(word['word'], str) or not word['word'].strip()):
                raise ValueError('Invalid word timestamps or text')
            previous = start
            word['start'], word['end'] = start, end
    except (KeyError, IndexError, TypeError, OverflowError) as exc:
        raise ValueError('Malformed Deepgram transcript') from exc
    segments, group = [], []
    for word in words:
        group.append(word)
        if word.get('punctuated_word', word['word']).endswith(('.', '?', '!')) or len(group) >= 12:
            segments.append(_segment(group))
            group = []
    if group:
        segments.append(_segment(group))
    return {'provider': 'deepgram', 'words': words, 'segments': segments}


def guard_outputs(outputs, sources=()):
    outputs = [Path(p) for p in outputs]
    resolved = [p.resolve() for p in outputs]
    if len(set(resolved)) != len(resolved):
        raise ValueError('Output paths collide')
    for path in outputs:
        if path.resolve() in {Path(p).resolve() for p in sources}:
            raise ValueError('Output would overwrite source')
        if path.exists() or path.is_symlink():
            raise ValueError('Output already exists; choose a new output path')


def shift_segments(segments, start, end):
    if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end <= start:
        raise ValueError('Invalid clip range')
    return [{'start': max(start, s['start']) - start,
             'end': min(end, s['end']) - start, 'text': s['text']}
            for s in segments if s['start'] < end and s['end'] > start]


def subtitle_text(segments, vtt=False):
    def stamp(seconds):
        ms = round(seconds * 1000)
        seconds, ms = divmod(ms, 1000)
        minutes, seconds = divmod(seconds, 60)
        hours, minutes = divmod(minutes, 60)
        return f"{hours:02}:{minutes:02}:{seconds:02}{'.' if vtt else ','}{ms:03}"
    result = 'WEBVTT\n\n' if vtt else ''
    for index, segment in enumerate(segments, 1):
        result += (f"{index}\n{stamp(segment['start'])} --> {stamp(segment['end'])}\n"
                   f"{segment['text']}\n\n")
    return result


def transcript_paths(prefix):
    return [Path(str(prefix) + ext) for ext in ('.json', '.srt', '.vtt')]


def write_transcript(data, prefix):
    paths = transcript_paths(prefix)
    guard_outputs(paths)
    contents = [json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + '\n',
                subtitle_text(data['segments']), subtitle_text(data['segments'], vtt=True)]
    for path, content in zip(paths, contents):
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('x', encoding='utf-8') as stream:
            stream.write(content)
    return paths


def _segment(words):
    return {'start': words[0]['start'], 'end': words[-1]['end'],
            'text': ' '.join(w.get('punctuated_word', w['word']) for w in words)}


def load_transcript(path):
    payload = json.loads(Path(path).read_text(encoding='utf-8'))
    if not isinstance(payload, dict):
        raise ValueError('Transcript JSON must be an object')
    if 'words' in payload:
        result = normalize({'results': {'channels': [{'alternatives': [{'words': payload['words']}]}]}})
    else:
        result = normalize(payload)
    if 'fixture_notice' in payload:
        result['fixture_notice'] = payload['fixture_notice']
    return result


def media_duration(source):
    try:
        result = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                                 '-of', 'json', str(source)], capture_output=True, text=True, check=True)
        duration = float(json.loads(result.stdout)['format']['duration'])
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError
        return duration
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError):
        raise RuntimeError('FFprobe could not determine a valid media duration') from None


def resolve_media(value, work, *, authorized_youtube=False):
    from urllib.parse import urlsplit
    parsed = urlsplit(str(value))
    if not parsed.scheme and not parsed.netloc:
        path = Path(value).resolve()
        if not path.is_file():
            raise ValueError('Local input media does not exist')
        return path
    if (parsed.scheme != 'https' or parsed.hostname not in
            {'youtube.com', 'www.youtube.com', 'm.youtube.com', 'youtu.be'}
            or parsed.username or parsed.password or parsed.port not in (None, 443)):
        raise ValueError('Only local media or YouTube HTTPS URLs are supported')
    if not authorized_youtube:
        raise ValueError('YouTube input requires --authorized-youtube (confirm usage rights)')
    import yt_dlp
    work = Path(work)
    options = {'format': 'bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080]/best',
               'merge_output_format': 'mp4', 'outtmpl': str(work / 'source.%(ext)s'),
               'noplaylist': True, 'writesubtitles': False, 'writeautomaticsub': False,
               'overwrites': False, 'quiet': True, 'no_warnings': True}
    try:
        with yt_dlp.YoutubeDL(options) as downloader:
            downloader.extract_info(str(value), download=True)
    except Exception:
        raise RuntimeError('YouTube download failed; check authorization, availability and yt-dlp') from None
    files = [p for p in work.glob('source.*') if p.suffix not in {'.part', '.ytdl'}]
    if len(files) != 1:
        raise RuntimeError('YouTube download did not produce exactly one media file')
    return files[0].resolve()


def common_parser(description):
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument('input', help='Local media or authorized YouTube HTTPS URL')
    parser.add_argument('--language', default='en', help='Deepgram language code, e.g. en or id')
    parser.add_argument('--model', default='nova-3')
    parser.add_argument('--allow-paid-api', action='store_true')
    parser.add_argument('--authorized-youtube', action='store_true', help='Confirm rights to download/use YouTube media')
    parser.add_argument('--env-file', type=Path, help='Explicit dotenv file; never modified')
    parser.add_argument('--transcript-json', type=Path, help='Reuse full source timeline offline')
    return parser


def get_transcript(args, source, work):
    if args.transcript_json:
        return load_transcript(args.transcript_json)
    audio = extract_audio(source, Path(work) / 'audio.wav')
    return transcribe(audio, allow_paid_api=args.allow_paid_api, language=args.language,
                      model=args.model, env_file=args.env_file)


def check_consent(args):
    if not args.transcript_json and not args.allow_paid_api:
        raise ValueError('Network transcription requires --allow-paid-api')


def main(argv=None):
    parser = common_parser('Deepgram-only transcription to word JSON, SRT and VTT')
    parser.add_argument('--output-prefix', required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        check_consent(args)
        guard_outputs(transcript_paths(args.output_prefix), [args.input, args.transcript_json]
                      if args.transcript_json else [args.input])
        args.output_prefix.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='.deepgram-', dir=args.output_prefix.parent) as work:
            source = resolve_media(args.input, work, authorized_youtube=args.authorized_youtube)
            data = get_transcript(args, source, work)
            paths = write_transcript(data, args.output_prefix)
        print(json.dumps({'outputs': list(map(str, paths))}))
        return 0
    except (ValueError, RuntimeError, OSError) as exc:
        parser.exit(1, f'Error: {exc}\n')


if __name__ == '__main__':
    main()
