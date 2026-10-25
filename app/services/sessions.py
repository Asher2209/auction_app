"""Signed-in devices: each login gets a UserSession row, so a user can see where they are signed in and end any of them.

The session cookie holds only the row's random id (session["sid"]). On every request the row must exist, belong to the
signed-in user and not be revoked, or the login ends: that is how "sign out" on one device reaches another one.
"""
import secrets
from datetime import timedelta

from flask import current_app, request, session

from ..extensions import db
from ..models import UserSession, utcnow
from ..ratelimit import client_ip

KEY = "sid"
TOUCH_EVERY = timedelta(minutes=5)  # how stale last_seen_at may get before a request refreshes it (saves a write per page)


def start(user):
    row = UserSession(id=secrets.token_urlsafe(32), user_id=user.id, ip=client_ip()[:45],
                      user_agent=(request.headers.get("User-Agent") or "")[:255])
    db.session.add(row)
    db.session.commit()
    session[KEY] = row.id
    return row


def current(user):
    """This browser's session row if it is still valid for `user`, else None (refreshing last_seen_at now and then)."""
    sid = session.get(KEY)
    row = db.session.get(UserSession, sid) if isinstance(sid, str) else None
    if row is None or row.user_id != user.id or row.revoked_at is not None:
        return None
    if utcnow() - row.last_seen_at > TOUCH_EVERY:
        row.last_seen_at = utcnow()
        db.session.commit()
    return row


def end_current():
    sid = session.get(KEY)
    row = db.session.get(UserSession, sid) if isinstance(sid, str) else None
    if row is not None and row.revoked_at is None:
        row.revoked_at = utcnow()
        db.session.commit()


def active(user):
    """The user's sessions that could still be in use: not revoked and younger than the login lifetime, newest first."""
    oldest = utcnow() - current_app.config["LOGIN_MAX_AGE"]
    return (user.sessions.filter(UserSession.revoked_at.is_(None), UserSession.created_at >= oldest)
            .order_by(UserSession.last_seen_at.desc()).all())


def revoke(user, sid):
    row = db.session.get(UserSession, sid)
    if row is None or row.user_id != user.id or row.revoked_at is not None:
        return False
    row.revoked_at = utcnow()
    db.session.commit()
    return True


def revoke_others(user, keep=None):
    """End every session of `user` except `keep` (the id of this browser's). Returns how many were ended."""
    rows = user.sessions.filter(UserSession.revoked_at.is_(None), UserSession.id != (keep or "")).all()
    now = utcnow()
    for row in rows:
        row.revoked_at = now
    db.session.commit()
    return len(rows)


BROWSERS = (("Edg/", "Edge"), ("OPR/", "Opera"), ("Firefox/", "Firefox"), ("Chrome/", "Chrome"), ("Safari/", "Safari"))
SYSTEMS = (("Windows", "Windows"), ("Android", "Android"), ("iPhone", "iPhone"), ("iPad", "iPad"), ("Mac OS X", "macOS"),
           ("CrOS", "ChromeOS"), ("Linux", "Linux"))


def device_label(user_agent):
    """A rough human name for a browser, e.g. "Chrome on Windows". Only for display: user agents are easy to fake."""
    ua = user_agent or ""
    browser = next((name for token, name in BROWSERS if token in ua), "Unknown browser")
    system = next((name for token, name in SYSTEMS if token in ua), None)
    return f"{browser} on {system}" if system else browser
