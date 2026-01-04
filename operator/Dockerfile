FROM ghcr.io/flant/shell-operator:latest

RUN apk --no-cache add python3 py3-pip && \
    pip3 install kubernetes requests --break-system-packages

ADD hooks /hooks

RUN chmod +x /hooks/smart-tuner.py
