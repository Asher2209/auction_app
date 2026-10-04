"""A small in-memory sliding-window rate limiter.

Good for a single-process deployment (the project's scope). With several worker processes each one keeps
its own counters, so the effective limit is multiplied; a shared store such as Redis would fix that.
The limiter lives on the app (app.extensions["limiter"]) so every app instance, including each test,
starts with a clean slate.
"""
import threading
import time
from collections import deque
from functools import wraps

from flask import current_app, jsonify, render_template, request
from flask_login import current_user

MAX_KEYS = 20000  # memory bound: stale keys are dropped when the table grows past this


class RateLimiter:
    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self._hits = {}
        self._lock = threading.Lock()

    def _prune(self, key, window, now):
        q = self._hits.get(key)
        if q is None:
            return None
        while q and q[0] <= now - window:
            q.popleft()
        if not q:
            del self._hits[key]
            return None
        return q

    def count(self, key, window):
        with self._lock:
            q = self._prune(key, window, self._clock())
            return len(q) if q else 0

    def hit(self, key, window):
        now = self._clock()
        with self._lock:
            if len(self._hits) > MAX_KEYS:
                for k in list(self._hits):
                    self._prune(k, window, now)
            self._hits.setdefault(key, deque()).append(now)

    def retry_after(self, key, limit, window):
        """Seconds until one more hit would be allowed; 0 if it is allowed now."""
        now = self._clock()
        with self._lock:
            q = self._prune(key, window, now)
            if not q or len(q) < limit:
                return 0
            oldest_that_matters = q[len(q) - limit]  # the hit that must expire before the count drops below `limit`
            return max(1, int(oldest_that_matters + window - now) + 1)

    def clear(self, key):
        with self._lock:
            self._hits.pop(key, None)


def limiter():
    return current_app.extensions["limiter"]


def client_ip():
    return request.remote_addr or "unknown"


def too_many(retry_after, wants_json=None):
    """A 429 response: JSON for API-style callers, the error page otherwise."""
    if wants_json is None:
        wants_json = request.headers.get("Accept", "").startswith("application/json") or request.is_json
    minutes = max(1, -(-retry_after // 60))
    message = f"Too many attempts. Please try again in {minutes} minute{'s' if minutes != 1 else ''}."
    if wants_json:
        response = jsonify(ok=False, error=message)
    else:
        response = current_app.make_response(render_template("error.html", code=429, message=message))
    response.status_code = 429
    response.headers["Retry-After"] = str(retry_after)
    return response


def limited(name, limit, window, by="ip", methods=("POST",)):
    """Decorator: allow `limit` requests per `window` seconds per client (by="ip") or signed-in user (by="user")."""

    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if request.method in methods:
                ident = current_user.get_id() if by == "user" and current_user.is_authenticated else client_ip()
                key = f"{name}:{ident}"
                wait = limiter().retry_after(key, limit, window)
                if wait:
                    return too_many(wait)
                limiter().hit(key, window)
            return view(*args, **kwargs)

        return wrapped

    return decorator
