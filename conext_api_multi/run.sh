#!/usr/bin/with-contenv bashio

echo "Starting run.sh - Generating config.json"
bashio::config > /app/raw_config.json || echo "Error fetching bashio config"
cat /app/raw_config.json || echo "Error reading raw_config.json"
jq '.gateways // []' /app/raw_config.json > /app/config.json || echo "Error processing config.json with jq"
echo "Starting NGINX"
nginx || echo "Error starting NGINX"
echo "Starting Flask app"
python3 /app/solarmonitor.py || echo "Error starting solarmonitor.py"
