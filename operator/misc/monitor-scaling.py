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
APP_STARTUP_TIME = int(os.getenv("APP_STARTUP_TIME", "30")) # Czas w sek. na "rozgrzanie" pody
FIB_STEP_SECONDS = 10  # Mnożnik dla ciągu Fibonacciego

# Parametry KEDA (Domyślne vs Panic)
DEFAULT_POLLING_INTERVAL = 30
PANIC_POLLING_INTERVAL = 5
DEFAULT_THRESHOLD = 10
PANIC_THRESHOLD = 5

CPU_INCREMENT = 0.1  # O ile zwiększamy CPU (w rdzeniach)
MAX_CPU_LIMIT = 2.0  # Górny pułap, którego operator nie przekroczy

ERROR_THRESHOLD_LOW = 0.1   # Mało błędów - wystarczy poprawić polling
ERROR_THRESHOLD_HIGH = 1.0  # Dużo błędów - pody ewidentnie nie wyrabiają, zwiększ CPU

def get_shell_operator_config():
    """Zwraca konfigurację dla shell-operatora przy starcie."""
    return {
        "configVersion": "v1",
        "schedule": [
            {
                "name": "check_metrics",
                "crontab": "*/10 * * * * *",  # Uruchamiaj co 10s (tick zegara)
                "allowFailure": True
            }
        ]
    }

def get_fibonacci_delay(level):
    """Zwraca opóźnienie w sekundach bazując na poziomie i ciągu Fibonacciego."""
    # Ciąg: 0, 1, 1, 2, 3, 5, 8, 13, 21...
    fib_sequence = [0, 1, 1, 2, 3, 5, 8, 13, 21, 34, 55]
    # Jeśli poziom wykracza poza listę, bierzemy ostatni element (max delay)
    fib_val = fib_sequence[level] if level < len(fib_sequence) else fib_sequence[-1]
    
    # Formuła: Czas startu aplikacji + (Fib * 10s)
    return APP_STARTUP_TIME + (fib_val * FIB_STEP_SECONDS)

def query_prometheus(query):
    """Wykonuje zapytanie do Prometheus API."""
    try:
        response = requests.get(
            f"{PROMETHEUS_URL}/api/v1/query",
            params={'query': query},
            timeout=5
        )
        response.raise_for_status()
        result = response.json()['data']['result']
        if result:
            return float(result[0]['value'][1])
        return 0.0
    except Exception as e:
        print(f"ERROR querying Prometheus: {e}")
        return 0.0

def parse_cpu(cpu_str):
    """Konwertuje formaty k8s (np. '100m', '0.5') na float (rdzenie)."""
    if str(cpu_str).endswith('m'):
        return float(cpu_str[:-1]) / 1000.0
    return float(cpu_str)

def format_cpu(cpu_val):
    """Konwertuje float na format 'm' dla Kubernetes."""
    return f"{int(cpu_val * 1000)}m"

def patch_deployment_resources(api_apps, namespace, deployment_name):
    """Zwiększa requesty i limity CPU o zadaną wartość."""
    try:
        deploy = api_apps.read_namespaced_deployment(deployment_name, namespace)
        # Zakładamy, że interesuje nas pierwszy kontener
        container = deploy.spec.template.spec.containers[0]
        
        current_cpu_req = parse_cpu(container.resources.requests.get('cpu', '0.1'))
        current_cpu_lim = parse_cpu(container.resources.limits.get('cpu', '0.1'))
        
        if current_cpu_lim >= MAX_CPU_LIMIT:
            print(f"Limit CPU ({MAX_CPU_LIMIT}) reached. No further scaling.")
            return

        new_req = format_cpu(current_cpu_req + CPU_INCREMENT)
        new_lim = format_cpu(current_cpu_lim + CPU_INCREMENT)

        patch_body = {
            "spec": {
                "template": {
                    "spec": {
                        "containers": [{
                            "name": container.name,
                            "resources": {
                                "requests": {"cpu": new_req},
                                "limits": {"cpu": new_lim}
                            }
                        }]
                    }
                }
            }
        }
        
        api_apps.patch_namespaced_deployment(deployment_name, namespace, patch_body)
        print(f"PATCH DEPLOYMENT: New CPU Request: {new_req}, Limit: {new_lim}")
    except Exception as e:
        print(f"ERROR patching deployment: {e}")

def main():
    # 1. Obsługa rejestracji hooka (tylko przy starcie operatora)
    if len(sys.argv) > 1 and sys.argv[1] == "--config":
        print(json.dumps(get_shell_operator_config()))
        sys.exit(0)

    # 2. Inicjalizacja klienta K8s
    try:
        config.load_incluster_config()
    except:
        # Fallback dla testów lokalnych
        config.load_kube_config()
    
    api = client.CustomObjectsApi()
    
    # 3. Pobierz aktualny stan ScaledObject
    try:
        so = api.get_namespaced_custom_object(
            group="keda.sh",
            version="v1alpha1",
            namespace=TARGET_NAMESPACE,
            plural="scaledobjects",
            name=TARGET_SO_NAME
        )
    except Exception as e:
        print(f"ERROR: Could not find ScaledObject {TARGET_SO_NAME}: {e}")
        sys.exit(1)

    # 4. Smart Wait Logic (Algorytm czasu)
    annotations = so['metadata'].get('annotations', {})
    last_run_ts = float(annotations.get('operator.smart-tuner/last-run', 0))
    backoff_level = int(annotations.get('operator.smart-tuner/backoff-level', 0))
    
    current_delay = get_fibonacci_delay(backoff_level)
    now_ts = datetime.datetime.now().timestamp()
    
    # Sprawdź czy minęło wystarczająco dużo czasu od ostatniej zmiany
    if now_ts < (last_run_ts + current_delay):
        print(f"SKIP: Waiting for cooldown. Next check in {int((last_run_ts + current_delay) - now_ts)}s")
        sys.exit(0)

    # 5. Pobierz metryki (PromQL)
    # 503 Rate (ostatnia minuta)
    error_query = f'sum(rate(istio_requests_total{{response_code="503", destination_service_name="{SERVICE_NAME}"}}[1m])) OR on() vector(0)'
    error_rate = query_prometheus(error_query)
    
    print(f"METRICS: 503 Rate = {error_rate}")

    # 6. Algorytm Decyzyjny
    patch_needed = False
    new_spec = {}
    new_backoff_level = backoff_level
    current_polling = so['spec'].get('pollingInterval', DEFAULT_POLLING_INTERVAL)
    target_deploy_name = so['spec']['scaleTargetRef'].get('name')

    if error_rate > 0.1: # PRÓG BŁĘDU (np. więcej niż 0.1 błędu na sekundę)
        print("!!! PANIC MODE ACTIVATED !!!")
        
        # Jeśli parametry nie są już w trybie panic, zmień je
        if current_polling != PANIC_POLLING_INTERVAL:
            new_spec['pollingInterval'] = PANIC_POLLING_INTERVAL
            # Przykład modyfikacji triggera (zakładamy, że pierwszy trigger to prometheus/http)
            triggers = so['spec'].get('triggers', [])
            if triggers:
                triggers[0]['metadata']['threshold'] = str(PANIC_THRESHOLD)
                new_spec['triggers'] = triggers
            patch_needed = True

        print(f"Scaling up resources for Deployment: {target_deploy_name}")
        patch_deployment_resources(api, TARGET_NAMESPACE, target_deploy_name)
        
        # Resetujemy backoff - sprawdzamy bardzo często (tylko startup time)
        new_backoff_level = 0 

    else:
        print("... System stable ...")
        # Jeśli jest stabilnie, a parametry są "spanikowane", przywracamy normę
        if current_polling == PANIC_POLLING_INTERVAL:
             print("Restoring default parameters.")
             new_spec['pollingInterval'] = DEFAULT_POLLING_INTERVAL
             triggers = so['spec'].get('triggers', [])
             if triggers:
                triggers[0]['metadata']['threshold'] = str(DEFAULT_THRESHOLD)
                new_spec['triggers'] = triggers
             patch_needed = True
             # Po naprawie nie zwiększamy poziomu od razu, trzymamy poziom 0 na jedną iterację
        else:
            # Jeśli parametry są w normie i brak błędów -> zwiększamy odstęp (Fibonacci)
            new_backoff_level += 1
            if new_backoff_level > 10: new_backoff_level = 10 # Cap

    # 7. Aplikowanie zmian (Patch)
    if patch_needed or new_backoff_level != backoff_level:
        patch_body = {
            "metadata": {
                "annotations": {
                    "operator.smart-tuner/last-run": str(now_ts),
                    "operator.smart-tuner/backoff-level": str(new_backoff_level)
                }
            }
        }
        if new_spec:
            patch_body["spec"] = new_spec
            print(f"APPLYING PATCH: {json.dumps(new_spec)}")
        
        api.patch_namespaced_custom_object(
            group="keda.sh",
            version="v1alpha1",
            namespace=TARGET_NAMESPACE,
            plural="scaledobjects",
            name=TARGET_SO_NAME,
            body=patch_body
        )
        print("State updated.")

if __name__ == "__main__":
    main()
