"""Outgoing email. Never raises: a mail outage must not break bidding, approvals or closing."""
import threading

from flask import current_app
from flask_mail import Message

from ..extensions import mail


def _deliver(app, msg):
    with app.app_context():
        try:
            mail.send(msg)
        except Exception:  # SMTP down, bad credentials, rejected recipient...
            app.logger.exception("Email delivery failed (to=%s, subject=%s)", msg.recipients, msg.subject)


def send_email(to, subject, body):
    app = current_app._get_current_object()
    if not to:
        return
    if not app.config.get("MAIL_SERVER") and not app.testing:
        # Development: no SMTP configured, so show what would have been sent.
        if app.config.get("APP_ENV") == "production":
            app.logger.warning("Email to %s skipped: no MAIL_SERVER configured (subject: %s)", to, subject)
        else:
            app.logger.info("[dev email] to=%s subject=%s\n%s", to, subject, body)
        return
    msg = Message(subject=subject, recipients=[to], body=body)
    if app.config["MAIL_ASYNC"]:
        threading.Thread(target=_deliver, args=(app, msg), daemon=True).start()
    else:
        _deliver(app, msg)
