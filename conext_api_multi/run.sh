#!/usr/bin/with-contenv bashio

echo "Starting run.sh - Generating config.json"
# Try UI config
if bashio::config.exists 'config'; then
    echo "UI config exists"
    bashio::config 'config' > /app/raw_config.json 2>/app/config_error.log || {
        echo "Error fetching bashio config, see /app/config_error.log"
        cat /app/config_error.log
        echo "Using hardcoded fallback config"
        echo '[{"name": "Insight_Facility_1", "ip": "192.168.10.106", "port": 503, "timeout": 5, "batteries": [], "powermeter": [], "inverters": [], "charge_controllers": [], "ags": [], "scp": [], "gridtie": []}]' > /app/config.json
    }
    echo "Raw UI config content:"
    cat /app/raw_config.json
else
    echo "No UI config found; using hardcoded fallback config"
    echo '[{"name": "Insight_Facility_1", "ip": "192.168.10.106", "port": 503, "timeout": 5, "batteries": [], "powermeter": [], "inverters": [], "charge_controllers": [], "ags": [], "scp": [], "gridtie": []}]' > /app/config.json
fi
jq '. // []' /app/raw_config.json > /app/config_processed.json 2>/app/jq_error.log || {
    echo "Error processing config with jq, see /app/jq_error.log"
    cat /app/jq_error.log
    echo '[{"name": "Insight_Facility_1", "ip": "192.168.10.106", "port": 503, "timeout": 5, "batteries": [], "powermeter": [], "inverters": [], "charge_controllers": [], "ags": [], "scp": [], "gridtie": []}]' > /app/config_processed.json
}
mv /app/config_processed.json /app/config.json
echo "Final /app/config.json content:"
cat /app/config.json 2>/app/config_final.log || echo "Error reading final config.json"
cat /app/config_final.log
echo "Starting NGINX"
nginx || echo "Error starting NGINX"
echo "Starting Flask app"
python3 /app/solarmonitor.py || echo "Error starting solarmonitor.py"
