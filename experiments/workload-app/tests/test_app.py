from app import app
from fastapi.testclient import TestClient

client = TestClient(app)

def test_cpu_endpoint():
    response = client.get("/cpu?loops=1000")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["loops"] == 1000

def test_mem_endpoint():
    response = client.get("/mem?mb=10")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["allocated_mb"] == 10
    assert "array_sum" in data

def test_io_endpoint():
    response = client.get("/io?size=1")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["written_mb"] == 1
    assert "file" in data

