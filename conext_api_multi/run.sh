#!/usr/bin/with-contenv bashio

echo "Starting run.sh - Generating config.json"
# Check if gateways config exists, use empty list if not
if bashio::config.exists 'gateways'; then
    bashio::config 'gateways' > /app/raw_config.json || echo "Error fetching bashio config"
    cat /app/raw_config.json || echo "Error reading raw_config.json"
    jq '. // []' /app/raw_config.json > /app/config.json || echo "Error processing config.json with jq"
else
    echo "No gateways config found; using empty list"
    echo '[]' > /app/config.json
fi
echo "Starting NGINX"
nginx || echo "Error starting NGINX"
echo "Starting Flask app"
python3 /app/solarmonitor.py || echo "Error starting solarmonitor.py"
