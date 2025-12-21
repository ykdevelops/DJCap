#!/bin/bash
# Start all AudioGiphy servers

cd "$(dirname "$0")"

echo "Starting AudioGiphy servers..."
echo ""

# Check if venv exists and use it, otherwise use system python3
if [ -f ".venv/bin/python3" ]; then
    PYTHON_CMD=".venv/bin/python3"
    echo "Using virtual environment Python"
else
    PYTHON_CMD="python3"
    echo "Using system Python"
fi

# Start djcap.py
echo "Starting djcap.py..."
nohup $PYTHON_CMD djcap.py > data/output/djcap.log 2>&1 &
echo $! > data/output/djcap.pid
echo "✓ djcap.py started (PID: $(cat data/output/djcap.pid))"

# Start djcap_processor.py
echo "Starting djcap_processor.py..."
nohup $PYTHON_CMD djcap_processor.py > data/output/djcap_processor.log 2>&1 &
echo $! > data/output/djcap_processor.pid
echo "✓ djcap_processor.py started (PID: $(cat data/output/djcap_processor.pid))"

# Start frontend/server.py
echo "Starting frontend/server.py..."
nohup $PYTHON_CMD frontend/server.py > data/output/frontend_server.log 2>&1 &
echo $! > data/output/frontend_server.pid
echo "✓ frontend/server.py started (PID: $(cat data/output/frontend_server.pid))"

sleep 2
echo ""
echo "Server status:"
ps -p $(cat data/output/djcap.pid 2>/dev/null) $(cat data/output/djcap_processor.pid 2>/dev/null) $(cat data/output/frontend_server.pid 2>/dev/null) 2>/dev/null | grep -v PID | wc -l | xargs echo "  Active processes:"

echo ""
echo "Frontend available at: http://localhost:8080"
echo ""
echo "To stop all servers, run: ./stop_servers.sh"

