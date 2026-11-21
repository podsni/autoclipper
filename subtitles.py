"""Bounded ASS cues; only provider word times drive highlighting."""
import math
import re
from pathlib import Path


def write_ass(words, start, end, path, style='clean', *, render_preset='standard', headline='', credit=''):
    if style not in {'clean', 'highlight'}:
        raise ValueError('Unknown subtitle style')
    # Centisecond quantization is inward, never extending beyond source bounds.
    duration = math.floor((end-start)*100 + 1e-7)
    visible = []
    cursor = 0
    for word in words:
        a = max(cursor, 0, math.ceil((word['start']-start)*100-1e-7))
        b = min(duration, math.floor((word['end']-start)*100+1e-7))
        text = re.sub(r'[\\{}\r\n]', '', word['text']).strip()
        # A very long token cannot wrap into unbounded lines.
        text = text[:24] + ('…' if len(text)>24 else '')
        if a < b and text:
            visible.append(dict(text=text, a=a, b=b, actual=word.get('timing_source') != 'interpolated'))
            cursor = b
    def fits_two_lines(items):
        lines, length = 1, 0
        for item in items:
            size = len(item['text'])
            if length and length + 1 + size > 25:
                lines += 1; length = 0
            length += size + (1 if length else 0)
        return lines <= 2

    groups, group = [], []
    for word in visible:
        if group and (not fits_two_lines(group+[word]) or len(group)>=5 or sum(len(w['text'])+1 for w in group)+len(word['text'])>46 or word['a']-group[-1]['b']>=40 or group[-1]['text'].endswith(('.', '?', '!', ';', ':')) or word['b']-group[0]['a']>250):
            groups.append(group); group=[]
        group.append(word)
    if group:
        groups.append(group)

    def timestamp(cs):
        return f'{cs//360000}:{cs//6000%60:02}:{cs//100%60:02}.{cs%100:02}'

    def line_text(group, active=None):
        lines, current, length = [], [], 0
        for i,w in enumerate(group):
            text = w['text']
            if current and length+1+len(text)>25:
                lines.append(' '.join(current)); current=[]; length=0
            length += len(text)+(1 if current else 0)
            if active == i:
                text = r'{\c&H0000FFFF&}' + text + r'{\c&H00FFFFFF&}'
            current.append(text)
        if current:
            lines.append(' '.join(current))
        return r'\N'.join(lines)

    events = []
    for group in groups:
        a,b = group[0]['a'],group[-1]['b']
        if style == 'highlight' and all(w['actual'] for w in group):
            boundaries = sorted({a,b,*[w['a'] for w in group],*[w['b'] for w in group]})
            for left,right in zip(boundaries,boundaries[1:]):
                active = next((i for i,w in enumerate(group) if w['a']<=left<w['b']),None)
                events.append((left,right,line_text(group,active)))
        else:
            events.append((a,b,line_text(group)))
    header = '''[Script Info]
ScriptType: v4.00+
PlayResX: 720
PlayResY: 1280
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,DejaVu Sans,40,&H00FFFFFF,&H0000FFFF,&H00101010,&H80000000,-1,0,0,0,100,100,0,0,1,2,0.5,2,60,60,220,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
'''
    overlays = ''
    if render_preset == 'reference':
        import textwrap
        def safe(value):
            return ' '.join(re.sub(r'[\\{}\r\n]', '', str(value)).split())
        title = safe(headline).upper()
        lines = textwrap.wrap(title, width=28, break_long_words=True)[:2]
        if len(textwrap.wrap(title, width=28, break_long_words=True)) > 2:
            lines[-1] = lines[-1].rstrip(' .') + '…'
        title_text = r'\N'.join(lines)
        credit_text = safe(credit)[:80]
        styles = 'Style: Title,DejaVu Sans,42,&H0000E5FF,&H0000E5FF,&H00101010,&H00000000,-1,0,0,0,100,100,0,0,1,1,0,8,40,40,135,1\nStyle: Credit,DejaVu Sans,20,&H00DDDDDD,&H00DDDDDD,&H00101010,&H00000000,0,0,0,0,100,100,0,0,1,1,0,2,40,40,180,1\n'
        header = header.replace('[Events]', styles+'\n[Events]')
        header = header.replace('DejaVu Sans,40,', 'DejaVu Sans,36,').replace(',60,60,220,1', ',60,60,270,1')
        if title_text:
            overlays += f'Dialogue: 1,0:00:00.00,{timestamp(duration)},Title,,0,0,0,,{title_text}\n'
        if credit_text:
            overlays += f'Dialogue: 1,0:00:00.00,{timestamp(duration)},Credit,,0,0,0,,{credit_text}\n'
    Path(path).write_text(header + ''.join(f'Dialogue: 0,{timestamp(a)},{timestamp(b)},Default,,0,0,0,,{text}\n' for a,b,text in events)+overlays,encoding='utf-8')
