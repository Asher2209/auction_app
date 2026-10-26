"""Sliding-window rate limiting, counted in this process (RateLimiter) or in Redis (RedisRateLimiter).

In memory is right for one process. With several web processes each would keep its own counters and the real limit
would be multiplied, so when REDIS_URL is set every process counts in Redis instead (see security.init_security).
Both have the same four methods. The limiter lives on the app (app.extensions["limiter"]) so every app instance,
including each test, starts with a clean slate.
"""
import threading
import time
import uuid
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



class RedisRateLimiter:
    """The same sliding window, shared by every process: one sorted set per key, scored by hit time.

    If Redis cannot be reached the limiter lets requests through and logs it: a brief outage should not lock every
    visitor out of the site. Login attempts are still checked against the password as usual.
    """
    PREFIX = "mintlot:rl:"

    def __init__(self, client, clock=time.time):
        self._r = client
        self._clock = clock

    def _key(self, key):
        return self.PREFIX + key

    def _live(self, key, window, now):
        """Drop hits older than the window; return the sorted set's name."""
        name = self._key(key)
        self._r.zremrangebyscore(name, "-inf", now - window)
        return name

    def _safely(self, fallback, fn):
        try:
            return fn()
        except Exception:  # redis.exceptions.RedisError and connection errors alike
            current_app.logger.exception("Rate limiter: Redis is unavailable, not limiting this request")
            return fallback

    def count(self, key, window):
        def run():
            now = self._clock()
            return self._r.zcard(self._live(key, window, now))
        return self._safely(0, run)

    def hit(self, key, window):
        def run():
            now = self._clock()
            name = self._key(key)
            pipe = self._r.pipeline()
            pipe.zremrangebyscore(name, "-inf", now - window)
            pipe.zadd(name, {f"{now:.6f}:{uuid.uuid4().hex[:8]}": now})
            pipe.expire(name, int(window) + 1)  # Redis forgets the key once nothing in it can matter
            pipe.execute()
        self._safely(None, run)

    def retry_after(self, key, limit, window):
        """Seconds until one more hit would be allowed; 0 if it is allowed now."""
        def run():
            now = self._clock()
            name = self._live(key, window, now)
            n = self._r.zcard(name)
            if n < limit:
                return 0
            (_, oldest_that_matters), = self._r.zrange(name, n - limit, n - limit, withscores=True)
            return max(1, int(oldest_that_matters + window - now) + 1)
        return self._safely(0, run)

    def clear(self, key):
        self._safely(None, lambda: self._r.delete(self._key(key)))


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
