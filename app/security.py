"""Cross-cutting security: response headers, error pages, production configuration checks, database integrity."""
import time

from flask import current_app, jsonify, render_template, request, session
from flask_login import current_user, logout_user
from flask_wtf.csrf import CSRFError
from sqlalchemy import event
from sqlalchemy.engine import Engine

from .ratelimit import RateLimiter

DEFAULT_SECRET = "dev-only-secret"
CDN_HOSTS = "https://cdn.jsdelivr.net https://cdnjs.cloudflare.com"


def content_security_policy(host):
    """No inline scripts or handlers, scripts only from this site and two pinned CDNs (which also carry SRI hashes)."""
    return "; ".join([
        "default-src 'self'",
        f"script-src 'self' {CDN_HOSTS}",
        f"style-src 'self' 'unsafe-inline' {CDN_HOSTS}",  # inline style="" attributes are used for sizing
        "img-src 'self' data: https://raw.githubusercontent.com https://images.pokemontcg.io",  # allow external card images
        "font-src 'self' https://cdn.jsdelivr.net",
        f"connect-src 'self' ws://{host} wss://{host}",  # Socket.IO
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        "frame-ancestors 'none'",
    ])


def production_problems(app):
    """Everything that must be fixed before running with APP_ENV=production."""
    cfg, problems = app.config, []
    secret = cfg.get("SECRET_KEY") or ""
    if secret == DEFAULT_SECRET or len(secret) < 32 or secret in ("change-me", "changeme"):
        problems.append("SECRET_KEY must be a random value of at least 32 characters")
    if not cfg.get("SESSION_COOKIE_SECURE"):
        problems.append("SECURE_COOKIES=1 is required so the session cookie is only sent over HTTPS")
    if cfg.get("ALLOW_TEST_EMAILS"):
        problems.append("ALLOW_TEST_EMAILS must be 0 (it accepts reserved test domains)")
    if cfg.get("LOCAL_CHAIN"):
        problems.append("LOCAL_CHAIN is a development-only demo chain and must be off")
    if app.debug:
        problems.append("debug mode must be off")
    if not str(cfg.get("APP_BASE_URL", "")).startswith("https://"):
        problems.append("APP_BASE_URL must be the public https:// address of the site")
    return problems


def init_security(app):
    app.extensions["limiter"] = RateLimiter()

    if app.config.get("APP_ENV") == "production":
        problems = production_problems(app)
        if problems:
            raise RuntimeError("Unsafe production configuration:\n  - " + "\n  - ".join(problems))

    @app.before_request
    def enforce_login_lifetime():
        """End a login that is older than LOGIN_MAX_AGE, or that carries no start time (e.g. forged or from an old version).

        This is checked on the server, so it cannot be extended by editing a cookie, and the session cookie itself
        stays a browser-session cookie: that keeps Flask-Login's 'strong' protection active (it is skipped for
        permanent sessions) and the login ends when the browser closes.
        """
        if current_user.is_authenticated:
            started = session.get("login_at")
            if not isinstance(started, int) or time.time() - started > app.config["LOGIN_MAX_AGE"].total_seconds():
                logout_user()
                session.clear()

    @app.after_request
    def security_headers(response):
        h = response.headers
        h.setdefault("X-Content-Type-Options", "nosniff")  # an uploaded file can never be sniffed into a script
        h.setdefault("X-Frame-Options", "DENY")
        h.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        h.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=()")
        h.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        h.setdefault("Content-Security-Policy", content_security_policy(request.host))
        if request.is_secure or app.config.get("SESSION_COOKIE_SECURE"):
            h.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        # pages for signed-in users are private: never keep them in shared caches or show them from history after logout
        if request.endpoint != "static" and current_user.is_authenticated:
            h.setdefault("Cache-Control", "no-store")
        return response

    def wants_json():
        return request.headers.get("Accept", "").startswith("application/json") or request.is_json

    def error(code, message):
        if wants_json():
            return jsonify(ok=False, error=message), code
        return render_template("error.html", code=code, message=message), code

    @app.errorhandler(CSRFError)
    def csrf_failed(_e):
        return error(400, "Your session expired or the form was not valid. Please go back, reload the page and try again.")

    @app.errorhandler(400)
    def bad_request(_e):
        return error(400, "That request could not be understood.")

    @app.errorhandler(405)
    def not_allowed(_e):
        return error(405, "That action is not allowed here.")

    @app.errorhandler(429)
    def throttled(_e):
        return error(429, "Too many requests. Please slow down and try again shortly.")

    @app.errorhandler(500)
    def server_error(_e):
        # no exception text, SQL or paths ever reach the browser; the details are in the server log
        return error(500, "Something went wrong on our side. Please try again.")


@event.listens_for(Engine, "connect")
def _sqlite_foreign_keys(dbapi_connection, _record):
    """SQLite ignores foreign keys unless asked: switch them on so the database enforces its own relationships."""
    if dbapi_connection.__class__.__module__.startswith("sqlite3"):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()
