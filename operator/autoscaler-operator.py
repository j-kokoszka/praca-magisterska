import kopf
import kubernetes
import logging

kubernetes.config.load_incluster_config()  # for in-cluster
# or use: kubernetes.config.load_kube_config() for local testing
api = kubernetes.client.AutoscalingV2Api()
custom_api = kubernetes.client.CustomObjectsApi()

@kopf.on.create('example.com', 'v1', 'autoscalerpolicies')
def create_autoscaler(spec, name, namespace, logger, **kwargs):
    target = spec.get('targetDeployment')
    mode = spec.get('mode', 'horizontal')
    minr = spec.get('minReplicas', 1)
    maxr = spec.get('maxReplicas', 5)

    if mode == 'horizontal':
        logger.info(f"Creating HPA for deployment '{target}'")
        create_hpa(namespace, target, minr, maxr, logger)
    elif mode == 'vertical':
        logger.info(f"Creating VPA for deployment '{target}'")
        create_vpa(namespace, target, logger)
    else:
        logger.warning(f"Unknown mode '{mode}' specified")

def create_hpa(namespace, deployment_name, minr, maxr, logger):
    hpa_manifest = {
        "apiVersion": "autoscaling/v2",
        "kind": "HorizontalPodAutoscaler",
        "metadata": {"name": f"{deployment_name}-hpa"},
        "spec": {
            "scaleTargetRef": {
                "apiVersion": "apps/v1",
                "kind": "Deployment",
                "name": deployment_name,
            },
            "minReplicas": minr,
            "maxReplicas": maxr,
            "metrics": [
                {
                    "type": "Resource",
                    "resource": {
                        "name": "cpu",
                        "target": {
                            "type": "Utilization",
                            "averageUtilization": 70
                        }
                    }
                }
            ]
        },
    }

    try:
        api.create_namespaced_horizontal_pod_autoscaler(namespace, hpa_manifest)
        logger.info(f"HPA {deployment_name}-hpa created.")
    except kubernetes.client.exceptions.ApiException as e:
        if e.status == 409:
            logger.info("HPA already exists, skipping.")
        else:
            raise

def create_vpa(namespace, deployment_name, logger):
    vpa_manifest = {
        "apiVersion": "autoscaling.k8s.io/v1",
        "kind": "VerticalPodAutoscaler",
        "metadata": {"name": f"{deployment_name}-vpa"},
        "spec": {
            "targetRef": {
                "apiVersion": "apps/v1",
                "kind": "Deployment",
                "name": deployment_name,
            },
            "updatePolicy": {
                "updateMode": "Auto"
            }
        },
    }

    api_vpa = kubernetes.client.CustomObjectsApi()
    try:
        api_vpa.create_namespaced_custom_object(
            group="autoscaling.k8s.io",
            version="v1",
            namespace=namespace,
            plural="verticalpodautoscalers",
            body=vpa_manifest,
        )
        logger.info(f"VPA {deployment_name}-vpa created.")
    except kubernetes.client.exceptions.ApiException as e:
        if e.status == 409:
            logger.info("VPA already exists, skipping.")
        else:
            raise

