import kopf
import kubernetes
from kubernetes.client import AppsV1Api, CustomObjectsApi, CoreV1Api
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


THRESHOLD = 70  # CPU utilization percentage

def load_config():
    try:
        kubernetes.config.load_incluster_config()
        print("[Operator] Using in-cluster config")
    except kubernetes.config.config_exception.ConfigException:
        kubernetes.config.load_kube_config()
        print("[Operator] Using local kubeconfig")


# Helper: calculate average CPU usage of pods
def get_average_cpu_usage(namespace: str, deployment_name: str):
    api = kubernetes.client.CustomObjectsApi()
    core = CoreV1Api()

    # Get pods for the deployment
    pods = core.list_namespaced_pod(namespace, label_selector=f"app={deployment_name}").items
    if not pods:
        return 0

    # Fetch metrics
    try:
        metrics = api.list_namespaced_custom_object(
            group="metrics.k8s.io", version="v1beta1", namespace=namespace, plural="pods"
        )
    except Exception:
        return 0

    usage_values = []

    for pod in pods:
        for m in metrics.get("items", []):
            if m["metadata"]["name"] == pod.metadata.name:
                cpu_str = m["containers"][0]["usage"]["cpu"]
                if cpu_str.endswith("n"):
                    cpu_millicores = int(cpu_str[:-1]) / 1_000_000
                else:
                    cpu_millicores = 0
                usage_values.append(cpu_millicores)

    return sum(usage_values) / len(usage_values)


@kopf.timer('apps', 'v1', 'deployments', interval=10)
def monitor_deployment(spec, name, namespace, **kwargs):
    # kubernetes.config.load_incluster_config()
    load_config()

    cpu_avg = get_average_cpu_usage(namespace, name)
    print(f"[Operator] Deployment {name} avg CPU: {cpu_avg}m")

    if cpu_avg > THRESHOLD:
        print(f"[Operator] CPU threshold exceeded! Switching from VPA -> HPA for {name}")
    else:
        print(f"[Operator] CPU usage normal. Keeping VPA for {name}")

