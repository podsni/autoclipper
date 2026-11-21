import base64
from fastapi.testclient import TestClient
import app as m


def auth(password='synthetic-test-password-only'):
    return {'Authorization': 'Basic ' + base64.b64encode(('autoclipper:' + password).encode()).decode()}


def test_network_requires_password(tmp_path):
    try:
        m.create_app(tmp_path, allow_network=True)
    except ValueError:
        return
    assert False, 'Network mode must reject empty password'


def test_authenticated_network_supports_ip_hosts_and_preserves_origin_guard(tmp_path):
    app = m.create_app(tmp_path, allow_network=True, network_password='synthetic-test-password-only')
    with TestClient(app, base_url='http://172.20.40.211:8787', client=('192.168.1.30', 12345)) as c:
        assert c.get('/api/health').status_code == 401
        assert c.get('/api/health', headers=auth('wrong')).status_code == 401
        assert c.get('/api/health', headers=auth()).status_code == 200
        assert c.get('/api/jobs', headers={**auth(), 'Origin':'http://evil.example'}).status_code == 403
        assert c.get('/api/health', headers={**auth(), 'Host':'evil.example:8787'}).status_code == 403
        assert c.get('/api/health', headers={**auth(), 'Origin':'http://172.20.40.211:8787'}).status_code == 200


def test_tailscale_ip_and_localhost_network_mode(tmp_path):
    app = m.create_app(tmp_path, allow_network=True, network_password='synthetic-test-password-only')
    with TestClient(app, base_url='http://100.72.125.8:8787', client=('100.100.100.100', 12500)) as c:
        assert c.get('/api/health', headers=auth()).status_code == 200
        assert c.get('/static/app.js').status_code == 401
    with TestClient(app, base_url='http://localhost:8787', client=('127.0.0.1', 12345)) as c:
        assert c.get('/api/health').status_code == 200


def test_default_remains_local_only(tmp_path):
    with TestClient(m.create_app(tmp_path), base_url='http://172.20.40.211:8787') as c:
        assert c.get('/api/health').status_code == 403
