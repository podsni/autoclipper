#!/usr/bin/env python3
"""Accurate reencoded clips with optional offline Deepgram transcript reuse."""
import json
import os
from pathlib import Path
import tempfile

import deepgram_transcribe as dg


def main(argv=None):
    parser = dg.common_parser('Deepgram-only clipper; times in source-relative seconds')
    parser.add_argument('--start', required=True, type=float)
    parser.add_argument('--end', required=True, type=float)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--vertical', action='store_true', help='Center crop to 720x1280')
    parser.add_argument('--burn', action='store_true', help='Burn shifted subtitles with libass')
    args = parser.parse_args(argv)
    try:
        dg.check_consent(args)
        dg.shift_segments([], args.start, args.end)
        dg.guard_outputs([args.output])
        output = args.output.resolve()
        if output.suffix.lower() != '.mp4':
            raise ValueError('--output must have .mp4 extension')
        prefix = output.with_suffix('')
        sources = [args.input] + ([args.transcript_json] if args.transcript_json else [])
        full_prefix = Path(str(prefix) + '.source')
        full_paths = dg.transcript_paths(full_prefix) if not args.transcript_json else []
        dg.guard_outputs([output, *dg.transcript_paths(prefix), *full_paths], sources)
        output.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='.deepgram-', dir=output.parent) as directory:
            work = Path(directory)
            source = dg.resolve_media(args.input, work, authorized_youtube=args.authorized_youtube)
            if args.end > dg.media_duration(source) + 0.001:
                raise ValueError('--end exceeds media duration')
            data = dg.get_transcript(args, source, work)
            if full_paths:
                dg.write_transcript(data, full_prefix)
            clipped = dict(data)
            clipped['segments'] = dg.shift_segments(data['segments'], args.start, args.end)
            clipped['words'] = [dict(w, start=max(args.start, w['start']) - args.start,
                                     end=min(args.end, w['end']) - args.start)
                                for w in data['words'] if w['start'] < args.end and w['end'] > args.start]
            (work / 'captions.srt').write_text(dg.subtitle_text(clipped['segments']), encoding='utf-8')
            filters = []
            if args.vertical:
                filters.append('scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280,setsar=1')
            if args.burn and clipped['segments']:
                filters.append('subtitles=captions.srt')
            command = ['-i', str(source), '-ss', str(args.start), '-t', str(args.end - args.start),
                       '-map', '0:v:0', '-map', '0:a:0?']
            if filters:
                command += ['-vf', ','.join(filters)]
            command += ['-c:v', 'libx264', '-preset', 'fast', '-crf', '20', '-pix_fmt', 'yuv420p',
                        '-c:a', 'aac', '-movflags', '+faststart', str(work / 'rendered.mp4')]
            dg.run_ffmpeg(command, cwd=work)
            os.link(work / 'rendered.mp4', output)
            dg.write_transcript(clipped, prefix)
        print(json.dumps({'video': str(output), 'subtitles': list(map(str, dg.transcript_paths(prefix))),
                          'source_transcript': list(map(str, full_paths))}))
        return 0
    except (ValueError, RuntimeError, OSError) as exc:
        parser.exit(1, f'Error: {exc}\n')


if __name__ == '__main__':
    main()
