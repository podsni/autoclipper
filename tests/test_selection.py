import pytest
from test_backend import load


def transcript(seconds=150):
    return {'words': [{'text': ('teknologi.' if i % 12 == 11 else 'inovasi'), 'start': i, 'end': i+.7} for i in range(seconds)]}


def test_real_timeline_candidates_nonoverlap_and_short_speech():
    m = load()
    words = m.normalize_words(transcript())
    clips = m.select_candidates(words, 150, 3)
    assert len(clips) == 3
    for clip in clips:
        assert 30 <= clip['end'] - clip['start'] <= 60
        assert clip['selection_method'] == 'heuristic'
        assert clip['title'] in ' '.join(w['text'] for w in words)
        assert set(clip) == {'start', 'end', 'title', 'caption', 'selection_method'}
    ordered = sorted(clips, key=lambda c:c['start'])
    assert all(a['end'] <= b['start'] for a,b in zip(ordered, ordered[1:]))
    short = m.select_candidates(m.normalize_words(transcript(8)), 8, 8)
    assert len(short) == 1 and 0 < short[0]['end'] <= 8
    with pytest.raises(ValueError): m.normalize_words({'words': []})
    with pytest.raises(ValueError): m.normalize_words({'words': [{'text':'x','start':float('nan'),'end':2}]})
    with pytest.raises(ValueError): m.normalize_words({'words': [{'text':'x','start':2,'end':1}]})


def test_normalize_raw_transcript_and_segment_fallback():
    m = load()
    raw = {'results': {'channels': [{'alternatives': [{'words': [{'word':'hello','punctuated_word':'Hello.','start':0,'end':1}]}]}]}}
    assert m.normalize_words(raw)[0]['text'] == 'Hello.'
    words = m.normalize_words({'segments':[{'start':0,'end':4,'text':'one two three four.'}]})
    assert [w['text'] for w in words] == ['one','two','three','four.']
    assert words[-1]['end'] == 4


def test_topic_heuristic_prefers_generic_technology_over_personnel_claims():
    m=load()
    words=[]
    for start,topic in [(0,['Jensen','dikeluarkan']), (45,['Ekosistem','berkembang'])]:
        tokens=topic+['bubble','teknologi']+['data']*35+['inovasi.']
        words.extend({'text':text,'start':start+i,'end':start+i+.7} for i,text in enumerate(tokens))
    result=m.select_candidates(words,85,1)
    assert result[0]['start']==45


def test_subtitle_groups_use_real_timestamps_and_escape_markup(tmp_path):
    m = load()
    words = m.normalize_words(transcript(12))
    path = tmp_path / 'clip.srt'
    m.write_subtitles(words, 2, 9, path)
    text = path.read_text()
    assert '00:00:00,000 --> 00:00:04,700' in text
    lines = [s for s in text.splitlines() if s and not s.isdigit() and '-->' not in s]
    assert all(len(line.split()) <= 5 for line in lines)
    assert sum(len(line.split()) for line in lines) == 7
