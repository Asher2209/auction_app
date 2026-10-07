"""Utility functions for ChainBid."""

from functools import wraps
from urllib.parse import urlparse

from flask import abort, request
from flask_login import current_user, login_required


def role_required(*roles):
    """Require a logged-in user holding one of `roles`; otherwise 401 redirect / 403."""
    def decorator(view):
        @wraps(view)
        @login_required
        def wrapped(*args, **kwargs):
            if not current_user.has_role(*roles):
                abort(403)
            return view(*args, **kwargs)
        return wrapped
    return decorator


def safe_redirect_target(target):
    """A same-site path (plus query) to redirect to, or None if `target` is not safe."""
    if not target or not isinstance(target, str) or len(target) > 2000:
        return None
    if any(ch in target for ch in "\\\r\n\t\x00"):
        return None
    parts = urlparse(target)
    if parts.scheme or parts.netloc:
        same_host = parts.scheme in ("http", "https") and parts.netloc == urlparse(request.host_url).netloc
        if same_host and parts.path.startswith("/") and not parts.path.startswith("//"):
            return parts.path + (f"?{parts.query}" if parts.query else "")
        return None
    if not target.startswith("/") or target.startswith("//"):
        return None
    return target


def is_safe_redirect(target):
    """Check if target is a safe redirect."""
    return safe_redirect_target(target) is not None


def like_pattern(text):
    """Contains-match pattern for ilike(..., escape="\\"); user-typed % and _ match literally."""
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


__all__ = ["role_required", "safe_redirect_target", "is_safe_redirect", "like_pattern"]
