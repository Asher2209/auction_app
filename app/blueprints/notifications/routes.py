from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from ...extensions import db
from ...models import Notification
from ...utils import safe_redirect_target
from . import bp

PER_PAGE = 20


def _own_or_404(notification_id):
    n = Notification.query.filter_by(id=notification_id, user_id=current_user.id).first()
    if n is None:  # 404 for other people's ids as well, so ids cannot be probed
        abort(404)
    return n


@bp.route("/")
@login_required
def index():
    only_unread = request.args.get("filter") == "unread"
    q = Notification.query.filter_by(user_id=current_user.id)
    if only_unread:
        q = q.filter_by(is_read=False)
    page = q.order_by(Notification.created_at.desc(), Notification.id.desc()).paginate(
        page=request.args.get("page", 1, type=int), per_page=PER_PAGE, error_out=False)
    return render_template("notifications/index.html", page=page, only_unread=only_unread)


@bp.route("/<int:notification_id>/go")
@login_required
def go(notification_id):
    """Open a notification: mark it read, then continue to the page it points at."""
    n = _own_or_404(notification_id)
    if not n.is_read:
        n.is_read = True
        db.session.commit()
    # only ever follow in-site paths ("/x", never "//host", "http://..." or backslash tricks)
    return redirect(safe_redirect_target(n.url) or url_for("notifications.index"))


@bp.route("/<int:notification_id>/read", methods=["POST"])
@login_required
def mark_read(notification_id):
    n = _own_or_404(notification_id)
    n.is_read = True
    db.session.commit()
    return redirect(url_for("notifications.index", **({"filter": "unread"} if request.form.get("filter") == "unread" else {})))


@bp.route("/read-all", methods=["POST"])
@login_required
def mark_all_read():
    Notification.query.filter_by(user_id=current_user.id, is_read=False).update({"is_read": True})
    db.session.commit()
    flash("All notifications marked as read.", "info")
    return redirect(url_for("notifications.index"))
