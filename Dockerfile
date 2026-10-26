# MintLot web and worker image. Build: docker build -t mintlot .   Local stack: docker compose up
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

# Exact versions from the lock file, installed before the code so this layer is reused while only code changes
COPY requirements.lock .
RUN pip install uv==0.12.23 && uv pip install --system -r requirements.lock && pip uninstall -y uv

COPY . .
# The app runs as an ordinary user that can write only where it must: uploads, QR codes and the instance folder
RUN useradd --create-home --uid 10001 mintlot \
 && mkdir -p app/static/uploads app/static/qrcodes instance \
 && chown -R mintlot:mintlot app/static/uploads app/static/qrcodes instance
USER mintlot

ENV FLASK_APP=run.py
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=4)"
CMD ["gunicorn", "-c", "deployment/gunicorn.conf.py", "run:app"]
