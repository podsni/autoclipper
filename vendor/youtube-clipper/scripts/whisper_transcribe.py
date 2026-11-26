#!/usr/bin/env python3
"""Local transcription with faster-whisper and portable timed subtitle utilities.

Drop-in replacement for the former Deepgram path: same CLI surface and the
same transcript JSON shape ({'provider', 'words', 'segments'}), so the app,
the clipper CLI and the cached-transcript readers keep working unchanged.
No audio leaves the machine and no API key is needed.

Model resolution for --model (or WHISPER_MODEL when the flag is omitted):
an existing directory is used as a local CTranslate2 model (offline), any
other value is a faster-whisper model name resolved through the Hugging Face
hub cache (downloaded once on first use). Default: "small".
"""

import argparse
import json
import math
import os
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

# faster-whisper lives in the user site-packages, which is not on sys.path
# when PYTHONNOUSERSITE=1. Add it explicitly so this script works no matter
# how the app server was launched.
try:
    import faster_whisper  # noqa: F401
except ImportError:
    import site as _site
    _site.addsitedir(_site.getusersitepackages())

DEFAULT_MODEL = "small"


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


def resolve_model(model):
    """Return (model_arg, local_files_only) for faster-whisper."""
    value = model or os.environ.get('WHISPER_MODEL') or DEFAULT_MODEL
    path = Path(value).expanduser()
    if path.is_dir():
        return str(path.resolve()), True
    return value, False


def read_wav_mono_f32(path):
    """Read a 16 kHz mono PCM16 WAV as a float32 numpy array (the skill's
    established faster-whisper calling convention: array input, not a path)."""
    import numpy as np
    with wave.open(str(path), 'rb') as wav:
        if wav.getnchannels() != 1 or wav.getsampwidth() != 2 or wav.getframerate() != 16000:
            raise ValueError('Expected 16 kHz mono PCM16 audio')
        frames = wav.readframes(wav.getnframes())
    audio = np.frombuffer(frames, dtype='<i2').astype(np.float32)
    audio *= 1.0 / 32768.0
    return audio


def validate_words(raw):
    """Validate and sanitize timed words into {'word','punctuated_word','start','end'}."""
    words = []
    previous = -1.0
    for item in raw:
        text = (item.get('punctuated_word') or item.get('text') or item.get('word') or '')
        text = str(text).strip()
        if not text or '\n' in text or '\r' in text or '-->' in text:
            continue
        start, end = float(item['start']), float(item['end'])
        if not math.isfinite(start) or not math.isfinite(end):
            continue
        if start < 0:
            start = 0.0
        if end <= start:
            end = start + 0.01
        if start < previous:
            # faster-whisper word timings are normally monotonic; clamp a
            # stray word instead of failing the whole transcript.
            start = previous
            if end <= start:
                end = start + 0.01
        words.append({'word': text, 'punctuated_word': text,
                      'start': start, 'end': end})
        previous = start
    if not words:
        raise ValueError('No timed words in transcript')
    return words


def build_transcript(words, *, provider='faster-whisper', model=None, language=None):
    words = validate_words(words)
    segments, group = [], []
    for word in words:
        group.append(word)
        if word['punctuated_word'].endswith(('.', '?', '!')) or len(group) >= 12:
            segments.append(_segment(group))
            group = []
    if group:
        segments.append(_segment(group))
    data = {'provider': provider, 'words': words, 'segments': segments}
    if model:
        data['model'] = model
    if language:
        data['language'] = language
    return data


def transcribe(audio, *, language='en', model=None):
    """Transcribe a 16 kHz mono WAV with faster-whisper (local, no network)."""
    import numpy as np  # noqa: F401  (kept explicit: array input is the contract)
    from faster_whisper import WhisperModel
    model_arg, local_only = resolve_model(model)
    audio = Path(audio)
    model_instance = WhisperModel(model_arg, device='cpu', compute_type='int8',
                                  cpu_threads=4, num_workers=1,
                                  local_files_only=local_only)
    pcm = read_wav_mono_f32(audio)
    segments, info = model_instance.transcribe(
        pcm, language=language or None, beam_size=5, vad_filter=True,
        word_timestamps=True)
    words = []
    for segment in segments:
        if not segment.words:
            raise ValueError('transcription did not return word timestamps')
        words.extend({'word': w.word, 'start': w.start, 'end': w.end}
                     for w in segment.words if w.word.strip())
    detected = getattr(info, 'language', None)
    return build_transcript(words, model=model_arg, language=detected or language)


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
        result = build_transcript(payload['words'])
    elif 'results' in payload:
        # Legacy Deepgram-shaped cache: same words, new provider label.
        raw = payload['results']['channels'][0]['alternatives'][0]['words']
        result = build_transcript(raw)
    else:
        raw = []
        for segment in payload.get('segments', []):
            tokens = segment['text'].split()
            start, end = float(segment['start']), float(segment['end'])
            if not tokens or not math.isfinite(start) or not math.isfinite(end) or start < 0 or end <= start:
                raise ValueError('Invalid transcript segment')
            for i, token in enumerate(tokens):
                raw.append({'word': token, 'start': start + (end - start) * i / len(tokens),
                            'end': start + (end - start) * (i + 1) / len(tokens)})
        result = build_transcript(raw)
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
    parser.add_argument('--language', default='en', help='Transcription language code, e.g. en or id')
    parser.add_argument('--model', default=None,
                        help='faster-whisper model name (e.g. small) or local model directory; '
                             'defaults to WHISPER_MODEL or "small"')
    parser.add_argument('--allow-paid-api', action='store_true',
                        help='Deprecated no-op: local transcription uses no paid API')
    parser.add_argument('--authorized-youtube', action='store_true', help='Confirm rights to download/use YouTube media')
    parser.add_argument('--env-file', type=Path, help='Deprecated no-op: no API key is read')
    parser.add_argument('--transcript-json', type=Path, help='Reuse full source timeline offline')
    return parser


def get_transcript(args, source, work):
    if args.transcript_json:
        return load_transcript(args.transcript_json)
    audio = extract_audio(source, Path(work) / 'audio.wav')
    return transcribe(audio, language=args.language, model=args.model)


def check_consent(args):
    # Local transcription needs no paid-API consent; kept so the clipper CLI
    # can call it unconditionally.
    return None


def main(argv=None):
    parser = common_parser('Local faster-whisper transcription to word JSON, SRT and VTT')
    parser.add_argument('--output-prefix', required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        check_consent(args)
        guard_outputs(transcript_paths(args.output_prefix), [args.input, args.transcript_json]
                      if args.transcript_json else [args.input])
        args.output_prefix.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='.whisper-', dir=args.output_prefix.parent) as work:
            source = resolve_media(args.input, work, authorized_youtube=args.authorized_youtube)
            data = get_transcript(args, source, work)
            paths = write_transcript(data, args.output_prefix)
        print(json.dumps({'outputs': list(map(str, paths))}))
        return 0
    except (ValueError, RuntimeError, OSError) as exc:
        parser.exit(1, f'Error: {exc}\n')


if __name__ == '__main__':
    main()
