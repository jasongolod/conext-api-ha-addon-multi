#!/usr/bin/with-contenv bashio

echo "Starting run.sh - Generating config.json"
# Debug /data/options.json
if [ -f /data/options.json ]; then
    echo "Found /data/options.json"
    ls -l /data/options.json > /app/permissions.log 2>&1
    cat /app/permissions.log
    cat /data/options.json > /app/raw_config.json 2>/app/config_error.log || {
        echo "Error reading /data/options.json, see /app/config_error.log"
        cat /app/config_error.log
        echo "Using hardcoded fallback config"
        echo '[{"name": "Insight_Facility_1", "ip": "192.168.10.106", "port": 503, "timeout": 5, "batteries": [], "inverters": [], "charge_controllers": []}, {"name": "Insight_Facility_2", "ip": "192.168.10.107", "port": 503, "timeout": 5, "batteries": [], "inverters": [], "charge_controllers": []}]' > /app/config.json
    }
else
    echo "No /data/options.json found; trying bashio config"
    bashio::config 'gateways' > /app/raw_config.json 2>/app/config_error.log || {
        echo "Error fetching bashio config, see /app/config_error.log"
        cat /app/config_error.log
        echo "Using hardcoded fallback config"
        echo '[{"name": "Insight_Facility_1", "ip": "192.168.10.106", "port": 503, "timeout": 5, "batteries": [], "inverters": [], "charge_controllers": []}, {"name": "Insight_Facility_2", "ip": "192.168.10.107", "port": 503, "timeout": 5, "batteries": [], "inverters": [], "charge_controllers": []}]' > /app/config.json
    }
fi
cat /app/raw_config.json 2>/dev/null || echo "Error reading raw_config.json"
jq '.gateways // []' /app/raw_config.json > /app/config_processed.json 2>/app/jq_error.log || {
    echo "Error processing config with jq, see /app/jq_error.log"
    cat /app/jq_error.log
    echo '[{"name": "Insight_Facility_1", "ip": "192.168.10.106", "port": 503, "timeout": 5, "batteries": [], "inverters": [], "charge_controllers": []}, {"name": "Insight_Facility_2", "ip": "192.168.10.107", "port": 503, "timeout": 5, "batteries": [], "inverters": [], "charge_controllers": []}]' > /app/config_processed.json
}
mv /app/config_processed.json /app/config.json
cat /app/config.json > /app/config_final.log 2>&1 || echo "Error reading final config.json"
echo "Starting NGINX"
nginx || echo "Error starting NGINX"
echo "Starting Flask app"
python3 /app/solarmonitor.py || echo "Error starting solarmonitor.py"
