FROM python:3.11-slim

WORKDIR /app

# Install dependencies
RUN pip install --no-cache-dir requests

# Copy monitor script
COPY monitor.py /app/monitor.py
RUN chmod +x /app/monitor.py

# Create data directory for state
RUN mkdir -p /data

# Environment variables (set via Coolify)
ENV CEREBRAS_API_KEY=""
ENV TELEGRAM_BOT_TOKEN=""
ENV TELEGRAM_CHAT_ID="-5223082150"
ENV SCAN_INTERVAL="3600"

# Run monitor
CMD ["python", "/app/monitor.py", "--interval", "3600"]
