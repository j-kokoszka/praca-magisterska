#!/bin/bash

SCRIPT="$1"

# 1. Run k6 and save to a temporary file
k6 run --out csv=temp_results.csv $SCRIPT

# 2. Check if the master file exists
if [ ! -f "master_results.csv" ]; then
    # If master doesn't exist, simply rename temp to master (keeps the header)
    mv temp_results.csv master_results.csv
else
    # If master exists, strip the header (first line) from temp and append to master
    tail -n +2 temp_results.csv >> master_results.csv
    rm temp_results.csv
fi

echo "Test finished. Data appended to master_results.csv"
