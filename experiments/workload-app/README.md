# Workload App

A simple application to generate CPU, memory, and I/O load for testing autoscaling mechanisms in Kubernetes.
Can be used to test HPA, VPA, KEDA, or custom MAPE-K controllers.

## Features

The application exposes three HTTP endpoints:

- /cpu – parameters: loops – generates CPU load by executing the specified number of loop iterations.
- /mem – parameters: mb – allocates a given amount of RAM in megabytes for a period of time.
- /io – parameters: size – simulates I/O operations by creating and writing data of the given size (MB).

Example usage:
GET /cpu?loops=1000000
GET /mem?mb=200
GET /io?size=50

## Requirements

- Python >= 3.9
- Poetry
- FastAPI
- Uvicorn
- NumPy

## Local Installation

1. Clone the repository and navigate to the project folder:
```bash
cd experiments/workload-app
```

2. Install dependencies using Poetry:
```bash
poetry install --no-root
```

3. Run the application:
```bash
poetry run uvicorn app:app --host 0.0.0.0 --port 8080
```

## Running with Docker

1. Build the Docker image:
```bash
docker build -t workload-app:latest .
```

2. Run the container:
```bash
docker run -p 8080:8080 workload-app:latest
```

## Integration with k6 / Test Scenarios

- Place JavaScript scenario files in ../k6/scenarios, e.g., burst.js, ramp.js, sine.js.
- Run a k6 scenario with Docker Compose:
```bash
docker-compose -f ../k6/docker-compose.yaml up --build
```

## Notes

- Endpoint parameters can be adjusted to test different autoscaling scenarios.
- The application can run locally in Docker or be deployed to a Kubernetes cluster.

