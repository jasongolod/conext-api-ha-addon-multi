#!/usr/bin/with-contenv bashio

# Generate config.json from add-on options
bashio::config 'gateways' | jq > /app/config.json

# Start NGINX
nginx

# Start the Flask app
python3 /app/solarmonitor.py
