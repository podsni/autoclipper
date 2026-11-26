# Third-party notices

## Youtube-clipper-skill

Upstream: https://github.com/op7418/Youtube-clipper-skill

Copyright (c) 2026 op7418. MIT License, preserved verbatim at `vendor/youtube-clipper/LICENSE`.

The upstream Python scripts are included under `vendor/youtube-clipper/scripts/`. `whisper_transcribe.py` and `whisper_clipper.py` are AutoClipper adaptations/additions for local faster-whisper STT (the former `deepgram_transcribe.py` / `deepgram_clipper.py` now only raise an error explaining the removal). The web dashboard, caption generation and render presets are additions to this integration.

This repository does not bundle FFmpeg, Node.js, model weights, third-party provider credentials or user media. Install runtime dependencies separately and comply with their licenses and provider terms.
