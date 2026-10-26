"""Health checks for the platform running the app. Plain JSON, no session, nothing secret in the reply.

  /healthz  the process is up (a failing one gets restarted)
  /readyz   it can serve: the database answers, and Redis too when REDIS_URL is set (until then, no traffic is sent)
"""
from flask import Blueprint, current_app, jsonify
from sqlalchemy import text

from ...extensions import db

bp = Blueprint("health", __name__)


@bp.route("/healthz")
def healthz():
    return jsonify(status="ok")


@bp.route("/readyz")
def readyz():
    checks = {}
    try:
        db.session.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception:
        current_app.logger.exception("Readiness: database check failed")
        db.session.rollback()
        checks["database"] = "failing"
    if current_app.config.get("REDIS_URL"):
        try:
            limiter = current_app.extensions["limiter"]
            limiter._r.ping()  # the Redis limiter's own client, so this checks the connection the app really uses
            checks["redis"] = "ok"
        except Exception:
            current_app.logger.exception("Readiness: Redis check failed")
            checks["redis"] = "failing"
    ok = all(v == "ok" for v in checks.values())
    return jsonify(status="ok" if ok else "failing", checks=checks), 200 if ok else 503
