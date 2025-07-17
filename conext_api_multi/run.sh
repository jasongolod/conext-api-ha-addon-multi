#!/usr/bin/with-contenv bashio

echo "Starting run.sh - Generating config.json"
# Log raw bashio output and errors
bashio::config 'gateways' > /app/raw_config.json 2>/app/config_error.log || {
    echo "Error fetching bashio config, see /app/config_error.log"
    cat /app/config_error.log
    echo "Using fallback empty config"
    echo '[]' > /app/config.json
}
cat /app/raw_config.json 2>/dev/null || echo "Error reading raw_config.json"
jq '. // []' /app/raw_config.json > /app/config.json 2>/app/jq_error.log || {
    echo "Error processing config.json with jq, see /app/jq_error.log"
    cat /app/jq_error.log
    echo '[]' > /app/config.json
}
echo "Starting NGINX"
nginx || echo "Error starting NGINX"
echo "Starting Flask app"
python3 /app/solarmonitor.py || echo "Error starting solarmonitor.py"
