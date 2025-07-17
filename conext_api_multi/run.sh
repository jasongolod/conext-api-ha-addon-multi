#!/usr/bin/with-contenv bashio

echo "Starting run.sh - Generating config.json"
# Write raw bashio config for debugging
bashio::config > /app/raw_config.json 2>/app/config_error.log || echo "Error fetching bashio config, see /app/config_error.log"
cat /app/raw_config.json || echo "Error reading raw_config.json"
# Extract gateways key, fallback to empty list if null or invalid
jq '.gateways // []' /app/raw_config.json > /app/config.json 2>/app/jq_error.log || echo "Error processing config.json with jq, see /app/jq_error.log"
echo "Starting NGINX"
nginx || echo "Error starting NGINX"
echo "Starting Flask app"
python3 /app/solarmonitor.py || echo "Error starting solarmonitor.py"
