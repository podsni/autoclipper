import subprocess
from pathlib import Path


def test_cli_exposes_explicit_network_and_password_file_options():
    root=Path(__file__).resolve().parents[1]
    result=subprocess.run([str(root/'.venv/bin/python'),str(root/'app.py'),'--help'],capture_output=True,text=True,check=True)
    assert '--allow-network' in result.stdout
    assert '--password-file' in result.stdout
