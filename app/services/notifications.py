"""Notifications: a stored in-app row, a live push to the user's open pages, and optionally an email.

`notify()` only stages the notification on the session. Once the surrounding transaction commits,
the staged items are pushed over Socket.IO and emailed; if it rolls back they are dropped, so nobody
is told about something that did not happen.
"""
from flask import current_app
from sqlalchemy import event
from sqlalchemy.orm import Session

from ..extensions import db, socketio
from ..models import Notification, User
from .mailer import send_email

PENDING = "pending_notifications"


def user_room(user_id):
    return f"user_{user_id}"


def notify(user_id, title, message, url=None, email=False):
    """Stage a notification. `url` is an in-site path; `email=True` also emails the user."""
    db.session.add(Notification(user_id=user_id, title=title[:150], message=message, url=url))
    item = {"user_id": user_id, "title": title[:150], "message": message, "url": url, "email_to": None}
    if email:
        user = db.session.get(User, user_id)
        item["email_to"] = user.email if user and user.is_active_user else None
    db.session().info.setdefault(PENDING, []).append(item)


def _email_body(item):
    base = current_app.config["APP_BASE_URL"]
    lines = [item["message"], ""]
    if item["url"]:
        lines += [f"View it here: {base}{item['url']}", ""]
    lines.append("You are receiving this because of your activity on ChainBid.")
    return "\n".join(lines)


@event.listens_for(Session, "after_commit")
def _deliver_after_commit(session):
    for item in session.info.pop(PENDING, []):
        payload = {k: item[k] for k in ("title", "message", "url")}
        socketio.emit("notification", payload, to=user_room(item["user_id"]))
        if item["email_to"]:
            send_email(item["email_to"], f"[ChainBid] {item['title']}", _email_body(item))


@event.listens_for(Session, "after_rollback")
def _drop_on_rollback(session):
    session.info.pop(PENDING, None)
