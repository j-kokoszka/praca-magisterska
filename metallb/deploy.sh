helm repo add metallb https://metallb.github.io/metallb
helm repo update
helm upgrade --install -n metallb --create-namespace metallb metallb/metallb
