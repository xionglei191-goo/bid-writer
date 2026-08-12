FROM node:22-bookworm-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.13-slim-bookworm
ARG DEBIAN_MIRROR=https://deb.debian.org
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app/backend
RUN sed -i "s|https\?://deb.debian.org/debian-security|${DEBIAN_MIRROR}/debian-security|g; s|https\?://deb.debian.org/debian|${DEBIAN_MIRROR}/debian|g" /etc/apt/sources.list.d/debian.sources \
    && (apt-get update && apt-cache show libreoffice-writer >/dev/null 2>&1 || (sed -i "s|${DEBIAN_MIRROR}/debian-security|https://deb.debian.org/debian-security|g; s|${DEBIAN_MIRROR}/debian|https://deb.debian.org/debian|g" /etc/apt/sources.list.d/debian.sources && apt-get update)) \
    && apt-get install -y --no-install-recommends libreoffice-writer poppler-utils fonts-noto-cjk curl p7zip-full libarchive-tools \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt
COPY backend/ /app/backend/
COPY --from=frontend /app/frontend/dist /app/frontend/dist
COPY README.md /app/README.md
RUN useradd --create-home --uid 10001 bidwriter \
    && mkdir -p /workspace/data /workspace/knowledge /workspace/delivery \
    && chown -R bidwriter:bidwriter /app /workspace
USER bidwriter
EXPOSE 8765
CMD ["uvicorn", "bid_writer_v2.app:app", "--host", "0.0.0.0", "--port", "8765"]
