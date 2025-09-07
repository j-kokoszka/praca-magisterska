# k6 Load Testing

This folder contains load testing scenarios for testing the FastAPI application `workload-app`.

## Scenarios
- `constant_load.js` – constant load with a fixed number of virtual users
- `ramp_up.js` – gradually increasing load
- `sudden_spike.js` – sudden spike in requests
- `random_mix.js` – random mix of different endpoints

## Running a scenario
You can run any scenario using the `runner.js` launcher with optional parameters:

```bash
cd experiments/load-testing/k6


# Run the constant load scenario on a local host
node runner.js --scenario constant_load --host http://localhost:8000 --vus 10 --duration 1m

# Run a sudden spike scenario on a Kubernetes service
node runner.js --scenario sudden_spike --host http://my-k8s-service:8000 --vus 50 --duration 30s
```


## Parameters

- `--scenario` – the scenario name (required)
- `--host` – the base URL of the FastAPI application (default: http://localhost:8000)
- `--vus` – number of virtual users (default: 5)
- `--duration` – duration of the test (default: 30s)

This setup allows you to easily test different load patterns and evaluate the behavior of autoscaling mechanisms.
