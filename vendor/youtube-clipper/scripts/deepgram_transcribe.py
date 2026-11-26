#!/usr/bin/env python3
"""Removed: Deepgram transcription is no longer supported.

AutoClipper now transcribes locally with faster-whisper — see
whisper_transcribe.py, which keeps the same CLI surface and transcript
JSON shape. This stub exists only so an old invocation fails loudly
instead of silently calling a paid API.
"""

raise RuntimeError(
    'Deepgram support was removed; use vendor/youtube-clipper/scripts/'
    'whisper_transcribe.py for local faster-whisper transcription')
