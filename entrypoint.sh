#!/bin/bash
set -e

export PORT=8000

# Generate nginx config
envsubst '$PORT' < /app/nginx.conf.template > /etc/nginx/nginx.conf

# Start all services (Jarvis API + Nginx)
exec /usr/bin/supervisord -c /etc/supervisor/conf.d/supervisord.conf
