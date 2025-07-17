#!/bin/sh

# For local testing: config.json is mounted directly, no HA bashio needed

# Start NGINX in background
nginx &

# Start the Flask app
python3 /app/solarmonitor.py
