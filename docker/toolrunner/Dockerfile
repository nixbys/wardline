# Single-purpose scan-execution sidecar for wardline.connectors.nmap_scan.
# See app.py's module docstring for why this is a separate container rather
# than a library import into the api/worker images.
FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends nmap \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir "fastapi>=0.115,<0.116" "uvicorn[standard]>=0.32,<0.33"

# Deliberately non-root: the endpoint only ever runs a TCP-connect-style
# scan (no `-sS`), which doesn't need NET_RAW/NET_ADMIN, so there's no
# reason this process should run as root or the container should be granted
# extra capabilities in docker-compose.yml.
RUN useradd --create-home --shell /usr/sbin/nologin scanner
WORKDIR /app
COPY app.py .
USER scanner

EXPOSE 8090
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8090"]
