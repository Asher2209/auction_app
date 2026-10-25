"""gunicorn settings for the MintLot web container (the Dockerfile's default command).

Flask-SocketIO in threading mode: one worker process with many threads, each WebSocket holding one thread. To serve
more people, run more containers behind the load balancer with REDIS_URL set; browsers connect by WebSocket only, so
no sticky sessions are needed. The background jobs run in the separate worker container (flask run-worker).
"""
import os

bind = f"0.0.0.0:{os.environ.get('PORT', '8000')}"
worker_class = "gthread"
workers = 1  # Socket.IO keeps its connections in the process: scale with containers, not workers
threads = int(os.environ.get("GUNICORN_THREADS", "100"))
timeout = 120
graceful_timeout = 30
keepalive = 5
accesslog = None  # the app logs one line per request itself (observability.py), with its request id
errorlog = "-"
