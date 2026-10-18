FROM node:24-bookworm-slim AS frontend
WORKDIR /build/website
COPY website/package.json website/package-lock.json ./
RUN npm ci
COPY website/ ./
RUN npm run build

FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_HUB_DISABLE_TELEMETRY=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libglib2.0-0 libgomp1 \
    && rm -rf /var/lib/apt/lists/*
COPY ml/requirements-cpu.txt ml/requirements.txt ./ml/
RUN pip install --no-cache-dir -r ml/requirements-cpu.txt \
    && pip install --no-cache-dir -r ml/requirements.txt
# Keep service constraints separate so an update does not invalidate CPU torch's layer.
COPY ml/requirements-service.txt ./ml/
RUN pip install --no-cache-dir -r ml/requirements-service.txt
COPY backend/pyproject.toml /tmp/backend-pyproject.toml
RUN python -c "import subprocess, sys, tomllib; \
    deps = tomllib.load(open('/tmp/backend-pyproject.toml', 'rb'))['project']['dependencies']; \
    subprocess.check_call([sys.executable, '-m', 'pip', 'install', '--no-cache-dir', *deps])"
COPY backend/ ./backend/
RUN pip install --no-cache-dir --no-deps --no-build-isolation ./backend
COPY ml/ ./ml/
COPY --from=frontend /build/website/dist ./website/dist
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')"
CMD ["uvicorn", "backend.app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
