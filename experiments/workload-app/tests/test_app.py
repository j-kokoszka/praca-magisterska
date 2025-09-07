from fastapi.testclient import TestClient
from app import app

client = TestClient(app)

def test_cpu_endpoint():
    response = client.get("/cpu?loops=1000")
    assert response.status_code == 200
    assert "CPU load executed" in response.text

def test_mem_endpoint():
    response = client.get("/mem?mb=10")
    assert response.status_code == 200
    assert "Memory allocated" in response.text

def test_io_endpoint():
    response = client.get("/io?size=1")
    assert response.status_code == 200
    assert "I/O simulated" in response.text

