#!/usr/bin/env python3
import os
import sys
import json
import datetime
import requests
from kubernetes import client, config

# --- KONFIGURACJA ZMIENNYCH ---
PROMETHEUS_URL = os.getenv("PROMETHEUS_URL", "http://prometheus-k8s.monitoring.svc:9090")
TARGET_NAMESPACE = os.getenv("TARGET_NAMESPACE", "default")
TARGET_SO_NAME = os.getenv("TARGET_SO_NAME", "my-app-scaledobject")
SERVICE_NAME = os.getenv("SERVICE_NAME", "my-app-service")
DEBUG_MODE = os.getenv("DEBUG", "false").lower() == "true"

APP_STARTUP_TIME = int(os.getenv("APP_STARTUP_TIME", "30"))
FIB_STEP_SECONDS = 10
STABILITY_QUERY_TEMPLATE = os.getenv("STABILITY_QUERY_TEMPLATE", 'sum(rate(istio_requests_total{{response_code=~"503|0", destination_service_name="{service}"}}[1m])) OR on() vector(0)')
KEDA_QUERY = os.getenv("KEDA_QUERY", 'sum(rate(istio_requests_total{{service="{service}"}}[{window}s]))')

# Parametry KEDA
DEFAULT_POLLING_INTERVAL = int(os.getenv("DEFAULT_POLLING_INTERVAL", "30"))
PANIC_POLLING_INTERVAL = int(os.getenv("PANIC_POLLING_INTERVAL", "5"))
DEFAULT_THRESHOLD = os.getenv("DEFAULT_THRESHOLD", "100")
PANIC_THRESHOLD = os.getenv("PANIC_THRESHOLD", "50")

# Parametry Zasobów
CPU_INCREMENT = float(os.getenv("CPU_INCREMENT", "0.1"))
MAX_CPU_LIMIT = float(os.getenv("MAX_CPU_LIMIT", "2.0"))
MIN_CPU_THRESHOLD = float(os.getenv("MIN_CPU_THRESHOLD", "0.2"))
STABLE_ITERATIONS_FOR_REDUCE = int(os.getenv("STABLE_ITERATIONS_FOR_REDUCE", "10"))
INITIAL_MIN_CPU = float(os.getenv("INITIAL_MIN_CPU", "0.2"))

# Progi arbitrażu (Błędy)
ERROR_THRESHOLD_LOW = float(os.getenv("ERROR_THRESHOLD_LOW", "50"))
ERROR_THRESHOLD_HIGH = float(os.getenv("ERROR_THRESHOLD_HIGH", "100"))

# --- FUNKCJE POMOCNICZE (Parsowanie/KEDA/CPU) ---

def log_debug(message):
    """Pomocnicza funkcja logowania warunkowego."""
    if DEBUG_MODE:
        print(f"DEBUG [{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]: {message}")

def get_shell_operator_config():
    return {
        "configVersion": "v1",
        "schedule": [{"name": "check_metrics", "crontab": "*/10 * * * * *", "allowFailure": True}]
    }

def get_fibonacci_delay(level):
    if DEBUG_MODE:
        return APP_STARTUP_TIME
    else:
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

def update_keda_spec(so_spec, polling, threshold):
    """
    Zwraca zmodyfikowany spec dla KEDA. 
    Synchronizuje pollingInterval z oknem czasowym zapytania PromQL.
    """
    so_spec['pollingInterval'] = polling
    
    if 'triggers' in so_spec and len(so_spec['triggers']) > 0:
        # 1. Aktualizacja progu (threshold)
        so_spec['triggers'][0]['metadata']['threshold'] = str(threshold)
        
        # 2. Obliczenie dynamicznego okna dla KEDA 
        # (Minimum 60s lub 2x polling, aby zapewnić stabilność rate())
        keda_query_window = max(polling * 2, 60)
        
        # 3. Wstrzyknięcie zaktualizowanego zapytania do ScaledObject
        # KEDA będzie teraz używać tego samego okna co Tuner
        so_spec['triggers'][0]['metadata']['query'] = KEDA_QUERY.format(
            service=SERVICE_NAME,
            window=keda_query_window
        )
        
        log_debug(so_spec)
        log_debug(f"Updated ScaledObject Spec -> Polling: {polling}s, Window: {keda_query_window}s")
        
    return so_spec

def modify_cpu(api_apps, namespace, deploy_name, direction="up"):
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

        patch_body = {"spec": {"template": {"spec": {"containers": [{"name": container.name, "resources": {"requests": {"cpu": new_val}, "limits": {"cpu": new_val}}}]}}}}
        api_apps.patch_namespaced_deployment(deploy_name, namespace, patch_body)
        print(f"ACTION: CPU scaled {direction} to {new_val}")
        return True
    except Exception as e:
        print(f"ERROR modifying CPU: {e}")
        return False

# --- TRYBY PRACY OPERATORA ---

def handle_panic_mode(api_apps, target_deploy, so_spec):
    """TRYB PANIC: Agresywne działanie - tniemy polling i zwiększamy CPU natychmiast."""
    print("!!! MODE: PANIC !!! High error rate detected.")
    
    # 1. Agresywna zmiana KEDA
    new_spec = update_keda_spec(so_spec, PANIC_POLLING_INTERVAL, PANIC_THRESHOLD)
    
    # 2. Natychmiastowe zwiększenie CPU
    modify_cpu(api_apps, TARGET_NAMESPACE, target_deploy, "up")
    
    return new_spec, 0, 0  # reset backoff i stable_iters

def handle_unstable_mode(api_apps, target_deploy, so_spec, current_polling):
    """TRYB UNSTABLE: Leniwe podejście - najpierw polling, potem CPU."""
    print("!!! MODE: UNSTABLE !!! Errors above low threshold.")
    new_spec = so_spec
    
    # KROK 1: Skróć polling jeśli jeszcze tego nie zrobiono
    if current_polling > PANIC_POLLING_INTERVAL:
        print("Decision: Adjusting KEDA polling to stabilize.")
        new_spec = update_keda_spec(so_spec, PANIC_POLLING_INTERVAL, PANIC_THRESHOLD)
    # KROK 2: Jeśli polling już jest niski, zacznij zwiększać CPU
    else:
        print("Decision: Polling already at minimum, increasing CPU.")
        modify_cpu(api_apps, TARGET_NAMESPACE, target_deploy, "up")
        
    return new_spec, 0, 0

def handle_stable_mode(api_apps, target_deploy, so_spec, current_polling, current_cpu, state):
    """TRYB STABLE: Optymalizacja pollingu, redukcja CPU i nauka minimum."""
    print("--- MODE: STABLE --- System healthy.")
    new_spec = so_spec
    new_stable_iters = state['stable_iters'] + 1
    new_backoff = min(state['backoff_level'] + 1, 10)
    learned_min = state['learned_min']

    # 1. Relaksacja Pollingu KEDA
    if current_polling < DEFAULT_POLLING_INTERVAL:
        print("Stable: Restoring default KEDA polling.")
        new_spec = update_keda_spec(so_spec, DEFAULT_POLLING_INTERVAL, DEFAULT_THRESHOLD)
        new_backoff = 0 # Sprawdź szybko po zmianie
    
    # 2. Relaksacja Zasobów (Scale Down)
    if new_stable_iters >= STABLE_ITERATIONS_FOR_REDUCE:
        if current_cpu > learned_min:
            print(f"Action: Reducing CPU towards learned-min ({learned_min})")
            if modify_cpu(api_apps, TARGET_NAMESPACE, target_deploy, "down"):
                new_stable_iters = 0
                new_backoff = 0
        else:
            # Optymalizacja minimum: jeśli system jest stabilny na learned_min przez 2x cykl, obniż minimum
            if new_stable_iters >= (STABLE_ITERATIONS_FOR_REDUCE * 2):
                learned_min = max(round(learned_min - 0.05, 2), MIN_CPU_THRESHOLD)
                print(f"LEARNING: High stability. Lowering learned-min-cpu to {learned_min}")
                new_stable_iters = 0

    return new_spec, new_backoff, new_stable_iters, learned_min

# --- GŁÓWNA FUNKCJA ---

def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--config":
        print(json.dumps(get_shell_operator_config()))
        sys.exit(0)

    try: config.load_incluster_config()
    except: config.load_kube_config()

    api_custom = client.CustomObjectsApi()
    api_apps = client.AppsV1Api()

    # Pobranie obiektu i stanu
    try:
        so = api_custom.get_namespaced_custom_object("keda.sh", "v1alpha1", TARGET_NAMESPACE, "scaledobjects", TARGET_SO_NAME)
    except Exception as e:
        print(f"ScaledObject {TARGET_SO_NAME} not found: {e}")
        sys.exit(1)

    annotations = so['metadata'].get('annotations', {})
    state = {
        "last_run": float(annotations.get('operator.smart-tuner/last-run', 0)),
        "backoff_level": int(annotations.get('operator.smart-tuner/backoff-level', 0)),
        "stable_iters": int(annotations.get('operator.smart-tuner/stable-iterations', 0)),
        "learned_min": float(annotations.get('operator.smart-tuner/learned-min-cpu', INITIAL_MIN_CPU))
    }

    # Sprawdzenie okna czasowego (Fibonacci)
    now_ts = datetime.datetime.now().timestamp()
    if now_ts < (state['last_run'] + get_fibonacci_delay(state['backoff_level'])):
        log_debug(f"empty run due to backoff [next run in {(state['last_run'] + get_fibonacci_delay(state['backoff_level']))-now_ts}")
        sys.exit(0)
    
    # 1. Obliczamy faktyczny czas, jaki upłynął od ostatniego uruchomienia
    # To jest nasze dynamiczne okno czasowe (lookback window)
    time_since_last_run = int(now_ts - state['last_run'])
    
    # 2. Ustawiamy minimalne okno (np. 60s), aby rate() miało sens statystyczny
    # Nawet jeśli skrypt uruchomi się po 10s, chcemy mieć stabilną próbkę
    query_window = max(time_since_last_run, 60)
    
    # 3. Dynamicznie modyfikujemy szablon zapytania
    # Zamieniamy "[1m]" na dynamiczne "[{window}s]"
    dynamic_query_template = STABILITY_QUERY_TEMPLATE.replace("[1m]", f"[{query_window}s]")
    

    # Pobranie metryk i aktualnych zasobów
    error_rate = query_prometheus(dynamic_query_template.format(service=SERVICE_NAME))
    target_deploy_name = so['spec']['scaleTargetRef'].get('name')
    deploy = api_apps.read_namespaced_deployment(target_deploy_name, TARGET_NAMESPACE)
    current_cpu = parse_cpu(deploy.spec.template.spec.containers[0].resources.requests.get('cpu'))
    current_polling = so['spec'].get('pollingInterval', DEFAULT_POLLING_INTERVAL)

    print(f"CHECK: Window={query_window}s, Errors={error_rate}, CPU={current_cpu}, Polling={current_polling}")

    # --- LOGIKA DECYZYJNA (TRYBY) ---
    
    new_so_spec = so['spec']
    learned_min = state['learned_min']

    if error_rate > ERROR_THRESHOLD_HIGH:
        # 1. TRYB PANIC
        new_so_spec, new_backoff, new_stable_iters = handle_panic_mode(api_apps, target_deploy_name, so['spec'])
        # Korekta learned_min jeśli Panic wystąpił na niskim CPU
        if current_cpu <= learned_min + 0.1:
            learned_min = round(current_cpu + 0.2, 1)
            print(f"LEARNING: Panic at low CPU. Bumping learned-min to {learned_min}")

    elif error_rate > ERROR_THRESHOLD_LOW:
        # 2. TRYB UNSTABLE
        new_so_spec, new_backoff, new_stable_iters = handle_unstable_mode(api_apps, target_deploy_name, so['spec'], current_polling)
        if current_cpu <= learned_min + 0.05:
            learned_min = round(current_cpu + 0.1, 1)

    else:
        # 3. TRYB STABLE
        new_so_spec, new_backoff, new_stable_iters, learned_min = handle_stable_mode(
            api_apps, target_deploy_name, so['spec'], current_polling, current_cpu, state
        )

    # Aktualizacja stanu w K8s
    patch_body = {
        "metadata": {
            "annotations": {
                "operator.smart-tuner/last-run": str(now_ts),
                "operator.smart-tuner/backoff-level": str(new_backoff),
                "operator.smart-tuner/stable-iterations": str(new_stable_iters),
                "operator.smart-tuner/learned-min-cpu": str(learned_min)
            }
        },
        "spec": new_so_spec
    }
    
    api_custom.patch_namespaced_custom_object("keda.sh", "v1alpha1", TARGET_NAMESPACE, "scaledobjects", TARGET_SO_NAME, patch_body)
    print("Decision cycle completed. State synchronized.")

if __name__ == "__main__":
    main()
