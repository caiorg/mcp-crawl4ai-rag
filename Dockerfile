FROM python:3.12-slim

ARG PORT=8051
# Port for noVNC web access
ARG NO_VNC_PORT=6080
# Internal VNC port that Xvnc will use (referenced by entrypoint.sh)
ARG VNC_PORT=5901

ENV NOVNC_PORT=${NO_VNC_PORT}
# Makes it available to entrypoint.sh and potentially the app
ENV VNC_PORT=${VNC_PORT}
ENV DEBUG="pw:api,pw:browser*" # Enable Playwright debug logging

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
    procps \
    libnss3 \
    libxss1 \
    libasound2 \
    libatk1.0-0 \
    libcairo2 \
    libcups2 \
    libdbus-1-3 \
    libexpat1 \
    libfontconfig1 \
    libgbm1 \
    libgconf-2-4 \
    libgdk-pixbuf2.0-0 \
    libglib2.0-0 \
    libgtk-3-0 \
    libnspr4 \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libx11-6 \
    libx11-xcb1 \
    libxcb1 \
    libxcomposite1 \
    libxcursor1 \
    libxdamage1 \
    libxext6 \
    libxfixes3 \
    libxi6 \
    libxrandr2 \
    libxrender1 \
    libxtst6 \
    ca-certificates \
    fonts-liberation \
    lsb-release \
    xdg-utils \
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
