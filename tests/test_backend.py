from pathlib import Path
import importlib.util
from fastapi.testclient import TestClient


def load():
    path = Path(__file__).parents[1] / 'app.py'
    assert path.exists(), 'backend entry point is missing'
    spec = importlib.util.spec_from_file_location('backend', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_health_and_durable_empty_jobs(tmp_path):
    m = load()
    with TestClient(m.create_app(tmp_path), base_url='http://localhost') as client:
        assert client.get('/api/health').json() == {'status': 'ok', 'deepgram_configured': m.deepgram_configured()}
        assert client.get('/api/jobs').json() == {'jobs': []}
        assert client.get('/api/jobs/missing').status_code == 404
