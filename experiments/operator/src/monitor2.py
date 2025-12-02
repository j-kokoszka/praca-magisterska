import kopf
import time
from kubernetes import client, config


DEPLOYMENT_NAME = "workload-app"
NAMESPACE = "default"
CPU_THRESHOLD_MILLICORES = 300  # np. 0.3 vCPU


def get_pod_cpu_millicores(metrics_client, namespace, pod_name):
    metrics = metrics_client.read_namespaced_pod_metrics(
        name=pod_name,
        namespace=namespace
    )
    total_nano = 0
    for c in metrics.containers:
        cpu = c.usage["cpu"]
        if cpu.endswith("n"):
            total_nano += int(cpu[:-1])
        elif cpu.endswith("m"):
            total_nano += int(cpu[:-1]) * 1_000_000
        else:
            raise ValueError(f"Nieznany format CPU: {cpu}")
    return total_nano / 1_000_000  # mCPU


# @kopf.timer("deployments", interval=10, namespace=NAMESPACE)
@kopf.timer("deployments", interval=10)
def monitor_deployment(spec, name, namespace, logger, **kwargs):
    """
    Timer handler: wywoływany co 10 sekund dla KAŻDEGO deploymentu w namespace.
    Filtrujemy tylko nasz jeden deployment.
    """
    if name != DEPLOYMENT_NAME:
        return  # ignorujemy nie ten deployment

    logger.info(f"Monitoring deployment: {name}")

    # kubernetes config
    config.load_incluster_config() if kopf.running_in_cluster() else config.load_kube_config()

    apps_api = client.AppsV1Api()
    core_api = client.CoreV1Api()
    metrics_api = client.MetricsV1beta1Api()

    # pobieramy deployment
    dep = apps_api.read_namespaced_deployment(name, namespace)
    labels = dep.spec.selector.match_labels

    pods = core_api.list_namespaced_pod(
        namespace=namespace,
        label_selector=",".join([f"{k}={v}" for k, v in labels.items()])
    ).items

    if not pods:
        logger.info("Brak podów.")
        return

    cpu_vals = []
    for pod in pods:
        try:
            cpu = get_pod_cpu_millicores(metrics_api, namespace, pod.metadata.name)
            cpu_vals.append(cpu)
        except Exception as e:
            logger.warning(f"Brak metrics dla {pod.metadata.name}: {e}")

    if not cpu_vals:
        logger.warning("Brak odczytów CPU.")
        return

    avg_cpu = sum(cpu_vals) / len(cpu_vals)

    logger.info(f"Średnie CPU: {avg_cpu:.0f} mCPU")

    if avg_cpu > CPU_THRESHOLD_MILLICORES:
        logger.warning("*** THRESHOLD PRZEKROCZONY: przełączam z VPA na HPA ***")

