"""What a running MintLot tells its operator: one log line per request, a request id to match reports to log lines,
and error reports to Sentry when SENTRY_DSN is set.

The request id comes from the proxy's X-Request-ID header when it sends a sane one, otherwise it is made here; it is
returned in the response and on every log line, so a "something went wrong" report can be found in the logs.
Sentry is told nothing personal: no cookies, no IP addresses, no user details (send_default_pii stays off).
"""
import logging
import re
import time
import uuid

from flask import g, request

REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{8,128}$")  # anything else from outside is replaced, never logged as given
log = logging.getLogger("mintlot.requests")


def request_id():
    return getattr(g, "request_id", "-")


class _RequestIdFilter(logging.Filter):
    def filter(self, record):
        from flask import has_request_context
        record.request_id = request_id() if has_request_context() else "-"
        return True


def init_app(app):
    if app.config.get("SENTRY_DSN"):
        import sentry_sdk
        from sentry_sdk.integrations.flask import FlaskIntegration
        sentry_sdk.init(dsn=app.config["SENTRY_DSN"], integrations=[FlaskIntegration()], send_default_pii=False,
                        environment=app.config.get("APP_ENV", "development"),
                        traces_sample_rate=app.config.get("SENTRY_TRACES_SAMPLE_RATE", 0.0))

    if not app.testing and not log.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [%(request_id)s] %(message)s"))
        handler.addFilter(_RequestIdFilter())
        log.addHandler(handler)
        log.setLevel(logging.INFO)
        log.propagate = False

    @app.before_request
    def start_request():
        given = request.headers.get("X-Request-ID", "")
        g.request_id = given if REQUEST_ID.match(given) else uuid.uuid4().hex
        g.request_started = time.perf_counter()

    @app.after_request
    def finish_request(response):
        response.headers["X-Request-ID"] = request_id()
        if not request.path.startswith("/static/") and request.endpoint not in ("health.healthz", "health.readyz"):
            took = (time.perf_counter() - g.get("request_started", time.perf_counter())) * 1000
            log.info("%s %s %s %.0fms", request.method, request.path, response.status_code, took)  # path only: no query string
        return response
