#!/bin/bash

# Check if Java process is running
if ! pgrep -f "java.*HytaleServer" > /dev/null 2>&1; then
    exit 1
fi

# Check if log file was updated recently (within last 5 minutes)
if [ -d "/data/logs" ]; then
    recent_logs=$(find /data/logs -name "*.log" -mmin -5 2>/dev/null | head -1)
    if [ -z "$recent_logs" ]; then
        # No recent log activity, but process is running
        # This might be normal during startup or idle periods
        exit 0
    fi
fi

exit 0
