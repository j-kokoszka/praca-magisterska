
for i in `kubectl get pods -o name`; do
  printf "$i"
  kubectl get $i -o jsonpath='
Scheduled: {.status.conditions[?(@.type=="PodScheduled")].lastTransitionTime}
Ready: {.status.conditions[?(@.type=="Ready")].lastTransitionTime}
{"\n"}'
done
