#!/bin/bash
# Restart all AudioGiphy servers (stop then start)

# Change to project root (two levels up from scripts/utils/)
cd "$(dirname "$0")/../.."

# Stop first
if [ -f "scripts/utils/stop_servers.sh" ]; then
    ./scripts/utils/stop_servers.sh
else
    pkill -9 -f "python.*djcap" 2>/dev/null
    pkill -9 -f "python.*frontend/server" 2>/dev/null
fi

sleep 1

# Start
if [ -f "scripts/utils/start_servers.sh" ]; then
    ./scripts/utils/start_servers.sh
else
    echo "start_servers.sh not found, starting manually..."
    # Fallback manual start
    nohup python3 djcap.py > data/output/djcap.log 2>&1 & echo $! > data/output/djcap.pid
    nohup python3 djcap_processor.py > data/output/djcap_processor.log 2>&1 & echo $! > data/output/djcap_processor.pid
    nohup python3 frontend/server.py > data/output/frontend_server.log 2>&1 & echo $! > data/output/frontend_server.pid
    echo "Servers restarted"
fi

