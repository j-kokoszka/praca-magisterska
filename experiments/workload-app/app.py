from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator
import logging
import hashlib
import numpy as np
import os
import tempfile
import time

app = FastAPI()

Instrumentator().instrument(app).expose(app)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(funcName)s | %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",  # ISO-like
)
logger = logging.getLogger(__name__)

@app.get("/cpu")
def cpu_intensive(loops: int = 1000000):
    """
    Symuluje CPU-bound workload.
    Wykonuje N pętli z operacjami hashującymi.
    """
    logger.info("Received /cpu request")
    start = time.time()
    data = b"test-data"
    for _ in range(loops):
        hashlib.sha256(data).digest()
    duration = time.time() - start
    logger.info(f"/cpu called with loops={loops}, duration={duration:.3f}s")
    return {"status": "ok", "loops": loops}

@app.get("/mem")
def mem_intensive(mb: int = 100):
    """
    Symuluje memory-bound workload.
    Alokuje tablicę o zadanym rozmiarze w MB.
    """
    size = mb * 1024 * 1024 // 8  # liczba elementów float64
    arr = np.ones(size, dtype=np.float64)
    # zatrzymujemy w pamięci na chwilę
    time.sleep(2)
    return {"status": "ok", "allocated_mb": mb, "array_sum": float(arr.sum())}

@app.get("/io")
def io_intensive(size: int = 10):
    """
    Symuluje I/O-bound workload.
    Tworzy plik tymczasowy o zadanym rozmiarze w MB i zapisuje go na dysku.
    """
    tmp_dir = tempfile.gettempdir()
    file_path = os.path.join(tmp_dir, "io_test_file")
    with open(file_path, "wb") as f:
        f.write(os.urandom(size * 1024 * 1024))
    return {"status": "ok", "written_mb": size, "file": file_path}

