from pathlib import Path
from test_backend import load


def test_checkout_contains_transcriber_and_uses_checkout_env():
    m=load()
    assert m.PROFILE==m.ROOT, 'Default env must belong to this checkout, not the developer profile'
    assert (m.CLIPPER/'scripts/whisper_transcribe.py').is_file()
    source=(m.ROOT/'app.py').read_text()
    assert not any(prefix in source for prefix in ('/home/', '/Users/', 'C:\\Users\\'))
    assert 'Path(sys.executable)' in source, 'Subprocesses must use the installed app interpreter'
