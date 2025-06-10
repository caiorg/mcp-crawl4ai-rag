#!/bin/sh
# entrypoint.sh

# Define ports - these should match arguments or be configurable
# Docker ARG/ENV variables will be available here if set in Dockerfile or docker run
NOVNC_PORT=${NOVNC_PORT:-6080} # Default if not set by Docker ARG/ENV
VNC_PORT=${VNC_PORT:-5901}   # Default VNC port Xvnc will be configured to use by pyvirtualdisplay

echo "Starting noVNC proxy (novnc_proxy) on port ${NOVNC_PORT}, targeting VNC server on localhost:${VNC_PORT}..."
# Using novnc_proxy directly.
# It will start websockify and point it to the VNC server (which pyvirtualdisplay will start on localhost:VNC_PORT).
/opt/novnc/utils/novnc_proxy --vnc localhost:${VNC_PORT} --listen ${NOVNC_PORT} &

# Add a small delay to ensure websockify starts before the main app, mostly for cleaner logs
sleep 2

echo "Starting MCP server (Python application)..."
# The original CMD of the Dockerfile
# Use exec to replace the shell process with the Python process,
# so that signals (like SIGTERM or SIGINT) are correctly passed to the Python app.
exec python src/crawl4ai_mcp.py
