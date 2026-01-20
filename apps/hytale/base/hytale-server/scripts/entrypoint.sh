#!/bin/bash
set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log() {
    echo -e "${GREEN}[Hytale]${NC} $1"
}

warn() {
    echo -e "${YELLOW}[Hytale]${NC} $1"
}

error() {
    echo -e "${RED}[Hytale]${NC} $1"
}

# Handle shutdown signals
JAVA_PID=""
shutdown() {
    if [ -n "$JAVA_PID" ]; then
        log "Shutting down server..."
        kill -TERM "$JAVA_PID" 2>/dev/null || true
        wait "$JAVA_PID" 2>/dev/null || true
    fi
    exit 0
}

trap shutdown SIGTERM SIGINT SIGHUP

# Fix permissions if running as root
if [ "$(id -u)" = "0" ]; then
    if [ "$UID" != "0" ]; then
        log "Fixing ownership to UID:$UID GID:$GID"
        chown -R "$UID:$GID" /data 2>/dev/null || true
        exec gosu "$UID:$GID" "$0" "$@"
    fi
fi

# Check for required files
SERVER_JAR="/data/HytaleServer.jar"
ASSETS_FILE="/data/Assets.zip"

if [ ! -f "$SERVER_JAR" ]; then
    error "HytaleServer.jar not found!"
    error "Please ensure HytaleServer.jar is present in /data."
    exit 1
fi

if [ ! -f "$ASSETS_FILE" ]; then
    error "Assets.zip not found!"
    error "Please ensure Assets.zip is present in /data."
    exit 1
fi

# Create required directories
mkdir -p /data/logs /data/mods /data/universe

# Build JVM arguments
JVM_ARGS=""

# Enable native access for Netty (required for Java 21+)
JVM_ARGS="$JVM_ARGS --enable-native-access=ALL-UNNAMED"

# Memory settings
if [ -n "$MAX_MEMORY" ]; then
    JVM_ARGS="$JVM_ARGS -Xmx$MAX_MEMORY"
elif [ -n "$MEMORY" ]; then
    JVM_ARGS="$JVM_ARGS -Xmx$MEMORY"
fi

if [ -n "$INIT_MEMORY" ]; then
    JVM_ARGS="$JVM_ARGS -Xms$INIT_MEMORY"
elif [ -n "$MEMORY" ]; then
    JVM_ARGS="$JVM_ARGS -Xms$MEMORY"
fi

# AOT cache support
AOT_FILE="/data/HytaleServer.aot"
if [ "$ENABLE_AOT" = "true" ] && [ -f "$AOT_FILE" ]; then
    log "AOT cache enabled"
    JVM_ARGS="$JVM_ARGS -XX:AOTCache=$AOT_FILE"
fi

# Add custom JVM options
if [ -n "$JVM_OPTS" ]; then
    JVM_ARGS="$JVM_ARGS $JVM_OPTS"
fi

# Build server arguments
SERVER_ARGS="--assets $ASSETS_FILE"
SERVER_ARGS="$SERVER_ARGS --bind $SERVER_HOST:$SERVER_PORT"

# Add extra arguments
if [ -n "$EXTRA_ARGS" ]; then
    SERVER_ARGS="$SERVER_ARGS $EXTRA_ARGS"
fi

# Debug mode
if [ "$DEBUG" = "true" ]; then
    log "Debug mode enabled"
    log "JVM Arguments: $JVM_ARGS"
    log "Server Arguments: $SERVER_ARGS"
fi

# Start server
log "Starting Hytale Server..."
log "Memory: ${MAX_MEMORY:-${MEMORY:-4G}}"
log "Port: $SERVER_PORT/udp"

cd /data

# Check if already authenticated
AUTH_FILE="/data/.auth_token"

if [ -f "$AUTH_FILE" ]; then
    log "Server already authenticated"
    java $JVM_ARGS -jar "$SERVER_JAR" $SERVER_ARGS &
    JAVA_PID=$!
else
    log "First run - will auto-trigger authentication..."
    log ""
    log "Watch the logs for the authentication link:"
    log "  docker compose logs -f"
    log ""
    log "After authenticating in browser, the server will be ready."
    log ""

    # Create a FIFO for sending commands
    FIFO="/tmp/hytale-input"
    rm -f "$FIFO"
    mkfifo "$FIFO"

    # Start server with FIFO as input
    tail -f "$FIFO" | java $JVM_ARGS -jar "$SERVER_JAR" $SERVER_ARGS &
    JAVA_PID=$!

    # Wait for server to boot
    sleep 25

    # Send auth command (device flow for headless servers)
    echo "/auth login device" > "$FIFO"

    # Wait for auth to complete, then enable persistence
    sleep 30
    echo "/auth persistence Encrypted" > "$FIFO"

    # Mark as auth attempted (actual token is managed by Hytale)
    touch "$AUTH_FILE"
fi

log "Server started with PID: $JAVA_PID"

# Wait for Java process
wait "$JAVA_PID"
exit_code=$?

log "Server stopped with exit code: $exit_code"
exit $exit_code
