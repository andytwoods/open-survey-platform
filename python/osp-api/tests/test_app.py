from fastapi.testclient import TestClient
from osp_api.app import create_app


def test_health():
    response = TestClient(create_app()).get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_version():
    response = TestClient(create_app()).get("/api/version")
    assert response.status_code == 200
    assert response.json() == {"name": "osp-api", "version": "0.0.0"}
