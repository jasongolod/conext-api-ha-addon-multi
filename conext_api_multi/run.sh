#!/usr/bin/with-contenv bashio

echo "Starting run.sh - Generating config.json"
# Try to fetch gateways config
if bashio::config.exists 'gateways'; then
    bashio::config 'gateways' > /app/raw_config.json 2>/app/config_error.log || {
        echo "Error fetching bashio config, see /app/config_error.log"
        cat /app/config_error.log
        echo "Using fallback config"
        cp /data/options.json /app/config.json 2>/app/cp_error.log || echo "Error copying options.json, see /app/cp_error.log"
    }
else
    echo "No gateways config in UI; using fallback config"
    cp /data/options.json /app/config.json 2>/app/cp_error.log || echo "Error copying options.json, see /app/cp_error.log"
fi
cat /app/config.json 2>/dev/null || echo "Error reading config.json"
jq '.gateways // []' /app/config.json > /app/config_processed.json 2>/app/jq_error.log || {
    echo "Error processing config with jq, see /app/jq_error.log"
    cat /app/jq_error.log
    echo '[]' > /app/config_processed.json
}
mv /app/config_processed.json /app/config.json
echo "Starting NGINX"
nginx || echo "Error starting NGINX"
echo "Starting Flask app"
python3 /app/solarmonitor.py || echo "Error starting solarmonitor.py"
