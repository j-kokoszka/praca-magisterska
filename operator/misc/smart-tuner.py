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

DEFAULT_QUERY = 'sum(rate(istio_requests_total{{response_code="503", destination_service_name="{service}"}}[1m])) OR on() vector(0)'
STABILITY_QUERY_TEMPLATE = os.getenv("STABILITY_QUERY_TEMPLATE", DEFAULT_QUERY)

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
    """
    Returns the configuration object required by Shell-operator.
    - configVersion: Specifies the Shell-operator API version.
    - schedule: Configures a recurring 'cron' trigger.
    - allowFailure: Ensures the operator continues even if this specific hook fails.
    """
    return {
        "configVersion": "v1",
        # Executes the hook 'check_metrics' every 10 seconds
        "schedule": [{"name": "check_metrics", "crontab": "*/10 * * * * *", "allowFailure": True}]
    }

def get_fibonacci_delay(level):
    """
    Calculates a dynamic delay based on the Fibonacci sequence.
    Args:
        level (int): The current retry level or depth.
    Returns:
        float: Total wait time (Base startup time + sequence-based delay).
    """
    # Predefined Fibonacci steps to avoid recursion overhead
    fib_sequence = [0, 1, 1, 2, 3, 5, 8, 13, 21, 34, 55]
    
    # Select value from sequence; cap at the last element if level exceeds list length
    fib_val = fib_sequence[level] if level < len(fib_sequence) else fib_sequence[-1]
    
    # Return total delay: constant startup overhead + (Fibonacci step * multiplier)
    return APP_STARTUP_TIME + (fib_val * FIB_STEP_SECONDS)

def query_prometheus(query):
    """
    Performs a PromQL query against the Prometheus HTTP API.
    
    Args:
        query (str): The PromQL expression to evaluate.
        
    Returns:
        float: The resulting metric value, or 0.0 if the query fails or is empty.
    """
    try:
        # Send GET request to the Instant Query endpoint with a 5s timeout
        response = requests.get(
            f"{PROMETHEUS_URL}/api/v1/query", 
            params={'query': query}, 
            timeout=5
        )
        response.raise_for_status() # Raise exception for 4xx/5xx errors
        
        # Extract the value from the JSON response: ['data']['result'][0]['value'][1]
        # result[0]['value'] typically looks like [timestamp, "value"]
        result = response.json()['data']['result']
        return float(result[0]['value'][1]) if result else 0.0
        
    except Exception as e:
        # Log failure and return a safe default to prevent script crash
        print(f"ERROR querying Prometheus: {e}")
        return 0.0

def parse_cpu(cpu_str):
    """
    Converts a Kubernetes CPU resource string into a float representing full cores.
    
    Examples:
        "500m" -> 0.5
        "2"    -> 2.0
        None   -> 0.1 (default)
    """
    # Fallback to a default of 0.1 cores (100m) if no value is provided
    if not cpu_str: 
        return 0.1
    
    # Check if the value is in millicores (e.g., "500m")
    if str(cpu_str).endswith('m'): 
        # Remove the 'm', convert to float, and divide by 1000 to get full cores
        return float(cpu_str[:-1]) / 1000.0
    
    # Otherwise, treat the string as a direct core count (e.g., "1" or "0.5")
    return float(cpu_str)

def format_cpu(cpu_val):
    """
    Converts a float value of cores back into a Kubernetes millicore string.
    
    Example:
        0.5 -> "500m"
        1.2 -> "1200m"
    """
    # Multiply by 1000 and truncate to an integer to append the 'm' suffix
    return f"{int(cpu_val * 1000)}m"

def modify_cpu(api_apps, namespace, deploy_name, direction="up"):
    """
    Increases or decreases the CPU resources of a specific Deployment.
    
    Args:
        api_apps: Kubernetes AppsV1Api client instance.
        namespace (str): The K8s namespace where the deployment resides.
        deploy_name (str): The name of the deployment to modify.
        direction (str): Either "up" (scale up) or "down" (scale down).
    """
    try:
        # 1. Fetch current deployment state from the Kubernetes API
        deploy = api_apps.read_namespaced_deployment(deploy_name, namespace)
        
        # 2. Target the first container in the pod template
        container = deploy.spec.template.spec.containers[0]
        
        # 3. Get current CPU requests; default to 0.1 (100m) if not set
        current_cpu = parse_cpu(container.resources.requests.get('cpu', '0.1'))

        # 4. Determine the new CPU value based on scaling direction
        if direction == "up":
            # Safety check: Do not exceed the predefined maximum CPU limit
            if current_cpu >= MAX_CPU_LIMIT: 
                return False
            # Calculate incremented value and format it for K8s (e.g., 0.5 -> "500m")
            new_val = format_cpu(current_cpu + CPU_INCREMENT)
        else:
            # Safety check: Do not drop below the minimum threshold
            if current_cpu <= MIN_CPU_THRESHOLD: 
                return False
            # Calculate decremented value, ensuring it never goes below MIN_CPU_THRESHOLD
            new_val = format_cpu(max(current_cpu - CPU_INCREMENT, MIN_CPU_THRESHOLD))

        # 5. Define the patch structure (Strategic Merge Patch format)
        # Note: This updates both 'requests' and 'limits' to the same value
        patch_body = {
            "spec": {
                "template": {
                    "spec": {
                        "containers": [{
                            "name": container.name,
                            "resources": {
                                "requests": {"cpu": new_val},
                                "limits": {"cpu": new_val}
                            }
                        }]
                    }
                }
            }
        }

        # 6. Apply the patch to the deployment in Kubernetes
        # This will trigger a rolling restart of the pods with the new resources
        api_apps.patch_namespaced_deployment(deploy_name, namespace, patch_body)
        
        print(f"ACTION: CPU scaled {direction} to {new_val}")
        return True

    except Exception as e:
        # Handle API errors (e.g., authentication issues or deployment not found)
        print(f"ERROR modifying CPU: {e}")
        return False

def main():
    # --- 1. SHELL-OPERATOR CONFIGURATION PHASE ---
    # Shell-operator calls the script with '--config' once at startup.
    # We return JSON describing when the script should run (e.g., every 10 seconds).
    if len(sys.argv) > 1 and sys.argv[1] == "--config":
        print(json.dumps(get_shell_operator_config()))
        sys.exit(0)

    # --- 2. KUBERNETES AUTHENTICATION ---
    # Attempt to load credentials.
    # 'incluster' is for running inside a Pod; 'kube_config' is for local testing (kubectl).
    try: 
        config.load_incluster_config()
    except: 
        config.load_kube_config()

    # Initialize Kubernetes API clients
    # api_custom: For KEDA ScaledObjects (Custom Resources)
    # api_apps: For standard Deployments
    api_custom = client.CustomObjectsApi()
    api_apps = client.AppsV1Api()

    # --- 3. STATE RETRIEVAL (KEDA ScaledObject) ---
    # The script uses annotations on the ScaledObject itself to persist state
    # across different execution cycles (acting like a database).
    try:
        so = api_custom.get_namespaced_custom_object(
            "keda.sh", "v1alpha1", TARGET_NAMESPACE, "scaledobjects", TARGET_SO_NAME
        )
    except Exception as e:
        print(f"ScaledObject not found: {e}")
        sys.exit(1)

    # --- 4. DATA PARSING FROM ANNOTATIONS ---
    # We extract custom metadata used to track the "Smart Tuning" progress:
    annotations = so['metadata'].get('annotations', {})

    # Timestamp of the last time the operator performed an action
    last_run_ts = float(annotations.get('operator.smart-tuner/last-run', 0))

    # The current Fibonacci backoff level (used if the system is unstable)
    backoff_level = int(annotations.get('operator.smart-tuner/backoff-level', 0))

    # How many iterations the system has remained in a 'stable' state
    stable_iters = int(annotations.get('operator.smart-tuner/stable-iterations', 0))

    # The minimum CPU floor calculated by the tuner over time
    learned_min_cpu = float(annotations.get('operator.smart-tuner/learned-min-cpu', INITIAL_MIN_CPU))


    # 2. Smart Wait
    # Calculate the required delay based on the current backoff level (e.g., 0, 1, 1, 2, 3, 5... minutes)
    current_delay = get_fibonacci_delay(backoff_level)
    now_ts = datetime.datetime.now().timestamp()
    
    # If the time elapsed since 'last_run_ts' is less than the required delay, exit early.
    # This prevents the script from constantly hitting the Prometheus API or K8s API.
    if now_ts < (last_run_ts + current_delay):
        sys.exit(0)


    # --- Configuration (usually at the top of the file) ---
    # We use a template string so we can still inject the SERVICE_NAME dynamically.
    # Default value is your original Istio 503 check.
    
    # 3. Metryki (Metrics Collection)
    # We generate the specific query by injecting the service name into our template.
    # This determines if the application is currently "unstable" (producing errors).
    error_query = STABILITY_QUERY_TEMPLATE.format(service=SERVICE_NAME)
    
    # Execute the PromQL query against the Prometheus API.
    # The result (error_rate) acts as the primary signal for the tuning logic.
    error_rate = query_prometheus(error_query)
    
    # Logging the diagnostic data:
    # - error_rate: Current health of the app.
    # - backoff_level: Current wait penalty (Fibonacci).
    # - stable_iters: How many consecutive 'healthy' checks we've had.
    print(f"CHECK: Metric Value = {error_rate}, Backoff Level = {backoff_level}, Stable Iters = {stable_iters}")

    # 4. Arbitration and Decision Logic
    # -----------------------------------------------------------
    
    # Initialize a dictionary to store any changes we might want to apply to the 
    # KEDA ScaledObject 'spec' (e.g., changing the pollingInterval).
    new_spec = {}
    
    # Local copies of the state variables fetched from annotations earlier.
    # If the logic below detects stability or instability, these 'new_' versions will be modified.
    new_backoff_level = backoff_level
    new_stable_iters = stable_iters
    
    # A boolean flag to track if we actually need to perform an API call (PATCH).
    # We only update the ScaledObject if this becomes True, saving unnecessary API traffic.
    patch_so = False
    
    # Fetch current operational parameters from the ScaledObject's specification.
    # 'pollingInterval' is how often KEDA checks the event source (e.g., RabbitMQ, Kafka).
    current_polling = so['spec'].get('pollingInterval', DEFAULT_POLLING_INTERVAL)
    
    # Retrieve the name of the Deployment (the 'scaleTargetRef') that KEDA is controlling.
    # This allows the script to remain generic and work for any deployment KEDA is attached to.
    target_deploy_name = so['spec']['scaleTargetRef'].get('name')
    
    # Access metadata annotations again for final comparison/verification.
    # These will be updated later with new timestamps and backoff levels.
    annotations = so['metadata'].get('annotations', {})

    # Use the AppsV1Api client to fetch the current live definition of the target Deployment.
    # This bypasses any cached data and goes straight to the Kubernetes API server
    # to ensure we have the most recent configuration.
    deploy = api_apps.read_namespaced_deployment(target_deploy_name, TARGET_NAMESPACE)
    
    # Dig into the Deployment's Pod template to find the CPU "requests" for the first container.
    # 1. deploy.spec.template.spec.containers[0] -> Accesses the primary application container.
    # 2. .resources.requests.get('cpu')          -> Retrieves the CPU value (e.g., "500m" or "0.5").
    # 3. parse_cpu(...)                          -> A helper function that converts K8s string units into a 
    #                                               float/decimal for mathematical comparison.
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
