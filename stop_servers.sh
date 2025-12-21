#!/bin/bash
# Stop all AudioGiphy servers

cd "$(dirname "$0")"

echo "Stopping AudioGiphy servers..."

# Kill by process name (more aggressive patterns)
pkill -9 -f "djcap.py" 2>/dev/null
pkill -9 -f "djcap_processor.py" 2>/dev/null
pkill -9 -f "frontend/server.py" 2>/dev/null
pkill -9 -f "frontend_server" 2>/dev/null

# Kill anything using port 8080 (frontend port)
lsof -ti:8080 2>/dev/null | xargs kill -9 2>/dev/null

# Also kill by PID files if they exist
if [ -f "data/output/djcap.pid" ]; then
    kill -9 $(cat data/output/djcap.pid) 2>/dev/null
    rm -f data/output/djcap.pid
fi

if [ -f "data/output/djcap_processor.pid" ]; then
    kill -9 $(cat data/output/djcap_processor.pid) 2>/dev/null
    rm -f data/output/djcap_processor.pid
fi

if [ -f "data/output/frontend_server.pid" ]; then
    kill -9 $(cat data/output/frontend_server.pid) 2>/dev/null
    rm -f data/output/frontend_server.pid
fi

sleep 1
echo "✓ All servers stopped"

