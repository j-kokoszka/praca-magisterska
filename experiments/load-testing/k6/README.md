# k6 Load Testing

Folder zawiera scenariusze obciążeniowe do testowania aplikacji FastAPI workload-app.

## Scenariusze
- constant_load.js – stały ruch
- ramp_up.js – stopniowo rosnące obciążenie
- sudden_spike.js – nagły spike
- random_mix.js – losowy miks endpointów

## Uruchamianie
Przykład:
```bash
node runner.js --scenario constant_load --host http://localhost:8000 --vus 10 --duration 1m
```

