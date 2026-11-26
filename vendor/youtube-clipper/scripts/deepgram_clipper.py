#!/usr/bin/env python3
"""Removed: the Deepgram-based clipper entry point is no longer supported.

Use whisper_clipper.py, which keeps the same CLI and imports the local
faster-whisper transcription module instead.
"""

raise RuntimeError(
    'Deepgram support was removed; use vendor/youtube-clipper/scripts/'
    'whisper_clipper.py instead')
