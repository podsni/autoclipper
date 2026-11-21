import base64
import pytest
from fastapi.testclient import TestClient
import app as m


def test_custom_username_with_explicit_short_password_opt_in(tmp_path):
    app=m.create_app(tmp_path,allow_network=True,network_username='customuser',network_password='testpw',allow_weak_password=True)
    header=lambda user:'Basic '+base64.b64encode((user+':testpw').encode()).decode()
    with TestClient(app,base_url='http://172.20.40.211:8787',client=('192.168.1.20',1234)) as c:
        assert c.get('/api/health',headers={'Authorization':header('customuser')}).status_code==200
        assert c.get('/api/health',headers={'Authorization':header('autoclipper')}).status_code==401


def test_short_password_still_rejected_without_opt_in(tmp_path):
    with pytest.raises(ValueError):
        m.create_app(tmp_path,allow_network=True,network_username='customuser',network_password='testpw')
