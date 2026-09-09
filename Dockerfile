# ---- Stage 1: build a self-contained virtualenv --------------------------- #
FROM python:3.12-slim AS builder

WORKDIR /app
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir -r requirements.txt

# ---- Stage 2: minimal runtime, non-root ----------------------------------- #
FROM python:3.12-slim AS runtime

# Create an unprivileged user to run the app.
RUN useradd --create-home --uid 10001 appuser

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000

WORKDIR /app
COPY app ./app
COPY migrations ./migrations

USER appuser
EXPOSE 8000

# Healthcheck hits /healthz (which also pings the DB). Respects $PORT so it
# works both in compose (8000) and on hosts that inject a PORT.
HEALTHCHECK --interval=30s --timeout=3s --start-period=15s --retries=3 \
  CMD python -c "import os,urllib.request,sys; p=os.getenv('PORT','8000'); \
sys.exit(0 if urllib.request.urlopen(f'http://127.0.0.1:{p}/healthz', timeout=2).status==200 else 1)"

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
