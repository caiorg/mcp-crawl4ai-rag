FROM python:3.12-slim

ARG PORT=8051
# Port for noVNC web access
ARG NO_VNC_PORT=6080
# Internal VNC port that Xvnc will use (referenced by entrypoint.sh)
ARG VNC_PORT=5901

ENV NOVNC_PORT=${NO_VNC_PORT}
# Makes it available to entrypoint.sh and potentially the app
ENV VNC_PORT=${VNC_PORT}

WORKDIR /app

# Install system dependencies for VNC, Xvfb, window manager, websockify, git
# The python:3.12-slim image runs as root by default.
RUN apt-get update && apt-get install -y --no-install-recommends \
    xvfb \
    tigervnc-standalone-server \
    fluxbox \
    websockify \
    git \
    net-tools \
    && rm -rf /var/lib/apt/lists/*

# Clone noVNC
RUN git clone https://github.com/novnc/noVNC.git /opt/novnc
# For stability, consider checking out a specific tag/version of noVNC, e.g.:
# RUN cd /opt/novnc && git checkout v1.4.0 && cd /app

# Install uv
RUN pip install uv

# Copy the MCP server files
COPY . .

# Install Python packages including pyvirtualdisplay
# Combining commands to reduce Docker layers
RUN uv pip install --system -e . pyvirtualdisplay && \
    crawl4ai-setup

# Copy entrypoint script and make it executable
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

EXPOSE ${PORT}
# Expose the noVNC port
EXPOSE ${NO_VNC_PORT}

# Command to run the entrypoint script
CMD ["/app/entrypoint.sh"]
