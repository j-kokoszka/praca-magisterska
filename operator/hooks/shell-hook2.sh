#!/usr/bin/env bash

if [[ $1 == "--config" ]] ; then
  echo '{"configVersion":"v1", "onStartup": 2}'
else
  echo "OnStartup shell hook 2"
fi
