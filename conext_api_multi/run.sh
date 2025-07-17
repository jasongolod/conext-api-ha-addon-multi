#!/usr/bin/with-contenv bashio

# Generate config.json from add-on options
bashio::config 'gateways' | jq > /app/config.json

# Start NGINX
nginx

# Start the Flask app with gunicorn
gunicorn -b 0.0.0.0:5000 -w 4 solarmonitor:app
