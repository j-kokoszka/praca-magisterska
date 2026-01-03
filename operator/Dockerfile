FROM ghcr.io/flant/shell-operator:latest
ADD hooks /hooks

# Instalujemy pythona i zależności
RUN apk --no-cache add python3 py3-pip && \
    pip3 install kubernetes requests --break-system-packages

# Kopiujemy nasz hook
# COPY hooks/monitor_scaling.py /hooks/monitor-scaling.py

# Nadajemy uprawnienia wykonywania
RUN chmod +x /hooks/monitor-scaling.py
