from pathlib import Path


def test_reference_controls_are_wired_to_job_submission():
    root=Path(__file__).resolve().parents[1]
    html=(root/'static/index.html').read_text()
    js=(root/'static/app.js').read_text()
    assert 'id="render-preset"' in html
    assert 'value="reference" selected' in html
    assert 'id="headline"' in html and 'maxlength="120"' in html
    assert "render_preset: $('render-preset').value" in js
    assert "headline: $('headline').value" in js
