#!/usr/bin/with-contenv bashio

echo "Starting run.sh - Generating config.json"
bashio::config 'gateways' | jq > /app/config.json || echo "Error generating config.json from bashio"

echo "Starting NGINX"
nginx || echo "Error starting NGINX"

echo "Starting Flask app"
python3 /app/solarmonitor.py || echo "Error starting solarmonitor.py"
