#!/usr/bin/env python3
import os
import sys
import json
import time
import datetime
import requests
from kubernetes import client, config

# --- KONFIGURACJA ZMIENNYCH ---
PROMETHEUS_URL = os.getenv("PROMETHEUS_URL", "http://prometheus-k8s.monitoring.svc:9090")
TARGET_NAMESPACE = os.getenv("TARGET_NAMESPACE", "default")
TARGET_SO_NAME = os.getenv("TARGET_SO_NAME", "my-app-scaledobject")
SERVICE_NAME = os.getenv("SERVICE_NAME", "my-app-service")

# Parametry algorytmu czasu
APP_STARTUP_TIME = int(os.getenv("APP_STARTUP_TIME", "30"))
FIB_STEP_SECONDS = 10

# Parametry KEDA
DEFAULT_POLLING_INTERVAL = 30
PANIC_POLLING_INTERVAL = 5
DEFAULT_THRESHOLD = "10"
PANIC_THRESHOLD = "5"

# Parametry Zasobów
CPU_INCREMENT = 0.1
MAX_CPU_LIMIT = 2.0
MIN_CPU_THRESHOLD = 0.2
STABLE_ITERATIONS_FOR_REDUCE = 10   # Wymagane 10 cykli spokoju przed obniżeniem CPU
INITIAL_MIN_CPU = 0.2               # Ta wartość będzie ewoluować w adnotacjach

# Progi arbitrażu
ERROR_THRESHOLD_LOW = 20
ERROR_THRESHOLD_HIGH = 1.0

def get_shell_operator_config():
    return {
        "configVersion": "v1",
        "schedule": [{"name": "check_metrics", "crontab": "*/10 * * * * *", "allowFailure": True}]
    }

def get_fibonacci_delay(level):
    fib_sequence = [0, 1, 1, 2, 3, 5, 8, 13, 21, 34, 55]
    fib_val = fib_sequence[level] if level < len(fib_sequence) else fib_sequence[-1]
    return APP_STARTUP_TIME + (fib_val * FIB_STEP_SECONDS)

def query_prometheus(query):
    try:
        response = requests.get(f"{PROMETHEUS_URL}/api/v1/query", params={'query': query}, timeout=5)
        response.raise_for_status()
        result = response.json()['data']['result']
        return float(result[0]['value'][1]) if result else 0.0
    except Exception as e:
        print(f"ERROR querying Prometheus: {e}")
        return 0.0

def parse_cpu(cpu_str):
    if not cpu_str: return 0.1
    if str(cpu_str).endswith('m'): return float(cpu_str[:-1]) / 1000.0
    return float(cpu_str)

def format_cpu(cpu_val):
    return f"{int(cpu_val * 1000)}m"

def modify_cpu(api_apps, namespace, deploy_name, direction="up"):
    """Zwiększa lub zmniejsza zasoby CPU Deploymentu."""
    try:
        deploy = api_apps.read_namespaced_deployment(deploy_name, namespace)
        container = deploy.spec.template.spec.containers[0]
        current_cpu = parse_cpu(container.resources.requests.get('cpu', '0.1'))
        
        if direction == "up":
            if current_cpu >= MAX_CPU_LIMIT: return False
            new_val = format_cpu(current_cpu + CPU_INCREMENT)
        else:
            if current_cpu <= MIN_CPU_THRESHOLD: return False
            new_val = format_cpu(max(current_cpu - CPU_INCREMENT, MIN_CPU_THRESHOLD))

        patch_body = {
            "spec": {"template": {"spec": {"containers": [{
                "name": container.name,
                "resources": {"requests": {"cpu": new_val}, "limits": {"cpu": new_val}}
            }]}}}
        }
        api_apps.patch_namespaced_deployment(deploy_name, namespace, patch_body)
        print(f"ACTION: CPU scaled {direction} to {new_val}")
        return True
    except Exception as e:
        print(f"ERROR modifying CPU: {e}")
        return False

def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--config":
        print(json.dumps(get_shell_operator_config())); sys.exit(0)

    try: config.load_incluster_config()
    except: config.load_kube_config()
    
    api_custom = client.CustomObjectsApi()
    api_apps = client.AppsV1Api()
    
    # 1. Pobierz ScaledObject i stan
    try:
        so = api_custom.get_namespaced_custom_object("keda.sh", "v1alpha1", TARGET_NAMESPACE, "scaledobjects", TARGET_SO_NAME)
    except Exception as e:
        print(f"ScaledObject not found: {e}"); sys.exit(1)

    annotations = so['metadata'].get('annotations', {})
    last_run_ts = float(annotations.get('operator.smart-tuner/last-run', 0))
    backoff_level = int(annotations.get('operator.smart-tuner/backoff-level', 0))
    stable_iters = int(annotations.get('operator.smart-tuner/stable-iterations', 0))
    learned_min_cpu = float(annotations.get('operator.smart-tuner/learned-min-cpu', INITIAL_MIN_CPU))
    
    # 2. Smart Wait
    current_delay = get_fibonacci_delay(backoff_level)
    now_ts = datetime.datetime.now().timestamp()
    if now_ts < (last_run_ts + current_delay):
        sys.exit(0)

    # 3. Metryki
    error_query = f'sum(rate(istio_requests_total{{response_code="503", destination_service_name="{SERVICE_NAME}"}}[1m])) OR on() vector(0)'
    error_rate = query_prometheus(error_query)
    print(f"CHECK: 503 Rate = {error_rate}, Backoff Level = {backoff_level}, Stable Iters = {stable_iters}")

    # 4. Arbitraż i Logika Decyzyjna
    new_spec = {}
    new_backoff_level = backoff_level
    new_stable_iters = stable_iters
    patch_so = False
    
    current_polling = so['spec'].get('pollingInterval', DEFAULT_POLLING_INTERVAL)
    target_deploy_name = so['spec']['scaleTargetRef'].get('name')

    annotations = so['metadata'].get('annotations', {})
    
    # Pobieramy aktualne CPU z Deploymentu
    deploy = api_apps.read_namespaced_deployment(target_deploy_name, TARGET_NAMESPACE)
    current_cpu = parse_cpu(deploy.spec.template.spec.containers[0].resources.requests.get('cpu'))

    if error_rate > ERROR_THRESHOLD_LOW:
        print(f"!!! UNSTABLE !!! Current CPU: {current_cpu}")
        new_stable_iters = 0
        new_backoff_level = 0 # Reaguj szybko w następnym kroku
        
        # KROK 1: Przyspiesz KEDA (Arbitraż: Polling najpierw)
        if current_polling > PANIC_POLLING_INTERVAL:
            print("Decision: Adjusting KEDA polling interval.")
            new_spec['pollingInterval'] = PANIC_POLLING_INTERVAL
            triggers = so['spec'].get('triggers', [])
            if triggers:
                triggers[0]['metadata']['threshold'] = PANIC_THRESHOLD
                new_spec['triggers'] = triggers
            patch_so = True

        # --- MECHANIZM WIEDZY ---
        # Jeśli mamy błędy, a nasze CPU jest blisko wyuczonego minimum, 
        # to znaczy, że minimum jest ustawione za nisko.
        if current_cpu <= learned_min_cpu + 0.05:
            new_learned_min = round(current_cpu + 0.1, 1)
            print(f"LEARNING: CPU {current_cpu} was not enough. Increasing learned-min-cpu to {new_learned_min}")
            learned_min_cpu = new_learned_min
        # ------------------------
        
        # KROK 2: Jeśli błędy są duże LUB polling już jest max -> zwiększ CPU
        if error_rate > ERROR_THRESHOLD_HIGH or current_polling <= PANIC_POLLING_INTERVAL:
            print("Decision: Scaling up CPU resources.")
            modify_cpu(api_apps, TARGET_NAMESPACE, target_deploy_name, "up")

    else:
        # SYSTEM STABILNY
        new_stable_iters = stable_iters + 1
        
        # Relaksacja Pollingu KEDA
        if current_polling < DEFAULT_POLLING_INTERVAL:
            print("Stable: Restoring default KEDA polling.")
            new_spec['pollingInterval'] = DEFAULT_POLLING_INTERVAL
            triggers = so['spec'].get('triggers', [])
            if triggers:
                triggers[0]['metadata']['threshold'] = DEFAULT_THRESHOLD
                new_spec['triggers'] = triggers
            patch_so = True
            new_backoff_level = 0 # Po zmianie parametrów sprawdź szybko czy ok
        else:
            # Jeśli polling w normie, zwiększamy odstęp czasowy
            new_backoff_level = min(backoff_level + 1, 10)

        # Relaksacja Zasobów (Scale Down)
        if new_stable_iters >= STABLE_ITERATIONS_FOR_REDUCE:
            print(f"Long-term stability reached ({new_stable_iters} iters). Attempting CPU scale-down.")
            if current_cpu > learned_min_cpu:
                print(f"Stable. Reducing CPU (learned-min is {learned_min_cpu})")
                if modify_cpu(api_apps, TARGET_NAMESPACE, target_deploy_name, "down"):
                    new_stable_iters = 0 # Resetuj licznik po zmianie
                    new_backoff_level = 0 # Sprawdź szybko czy po obniżeniu CPU błędy nie wrócą
            else:
                print(f"Stable, but reached learned-min-cpu ({learned_min_cpu}). Holding position.")

    # 5. Aktualizacja Stanu
    patch_body = {
        "metadata": {
            "annotations": {
                "operator.smart-tuner/last-run": str(now_ts),
                "operator.smart-tuner/backoff-level": str(new_backoff_level),
                "operator.smart-tuner/stable-iterations": str(new_stable_iters),
                "operator.smart-tuner/learned-min-cpu": str(learned_min_cpu)
            }
        }
    }
    if patch_so:
        patch_body["spec"] = new_spec
    
    api_custom.patch_namespaced_custom_object("keda.sh", "v1alpha1", TARGET_NAMESPACE, "scaledobjects", TARGET_SO_NAME, patch_body)
    print("State synchronized to Kubernetes.")

if __name__ == "__main__":
    main()
