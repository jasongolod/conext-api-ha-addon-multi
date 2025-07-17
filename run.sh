#!/usr/bin/with-contenv bashio

# Generate config.json from options
bashio::config 'gateways' | jq > /app/config.json

# Start NGINX
nginx

# Start the app
python3 /app/solarmonitor.py
