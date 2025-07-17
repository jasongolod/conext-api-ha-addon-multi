#!/usr/bin/with-contenv bashio

# Generate config.json from add-on options
bashio::config 'gateways' | jq > /app/config.json

# Start NGINX in background
nginx &

# Short delay to ensure NGINX starts
sleep 1

# Start the Flask app with gunicorn (4 workers for better handling)
gunicorn --bind 0.0.0.0:5000 --workers 4 solarmonitor:app
