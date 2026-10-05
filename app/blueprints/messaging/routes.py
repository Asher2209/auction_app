from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import or_

from ...extensions import db
from ...models import Message, Product
from ...services.notifications import notify
from ...utils import role_required, safe_redirect_target
from . import bp


@bp.route("/")
@login_required
def inbox():
    """View all messages (sent and received)."""
    page = request.args.get("page", 1, type=int)

    # Get all messages where user is sender or recipient
    messages = (Message.query
                .filter(or_(Message.sender_id == current_user.id,
                           Message.recipient_id == current_user.id))
                .order_by(Message.sent_time.desc())
                .paginate(page=page, per_page=20, error_out=False))

    # Count unread messages
    unread = Message.query.filter_by(recipient_id=current_user.id, read_time=None).count()

    return render_template("messaging/inbox.html", messages=messages, unread=unread)


@bp.route("/send/<int:product_id>", methods=["GET", "POST"])
@login_required
def send_message(product_id):
    """Send a message about a product."""
    product = Product.query.get_or_404(product_id)

    # Can only message if you're not the seller
    if product.seller_id == current_user.id:
        flash("You cannot message yourself.", "warning")
        return redirect(url_for("auctions.detail", auction_id=product.auction.id if product.auction else product_id))

    if request.method == "POST":
        subject = request.form.get("subject", "").strip()
        body = request.form.get("body", "").strip()

        if not subject or not body:
            flash("Subject and message cannot be empty.", "danger")
            return redirect(url_for("messaging.send_message", product_id=product_id))

        msg = Message(
            sender_id=current_user.id,
            recipient_id=product.seller_id,
            product_id=product_id,
            subject=subject,
            body=body
        )
        db.session.add(msg)
        db.session.commit()

        # Notify seller
        notify(product.seller_id, "New message received",
               f'{current_user.name} messaged you about "{product.title}": {subject}',
               url=url_for("messaging.view_conversation", product_id=product_id, user_id=current_user.id),
               email=True)

        flash("Message sent!", "success")
        return redirect(url_for("messaging.inbox"))

    return render_template("messaging/send.html", product=product)


@bp.route("/conversation/<int:product_id>/<int:user_id>")
@login_required
def view_conversation(product_id, user_id):
    """View conversation with a user about a product."""
    product = Product.query.get_or_404(product_id)
    other_user_id = user_id

    # Verify user is part of conversation
    if current_user.id != product.seller_id and current_user.id != other_user_id:
        flash("You don't have access to this conversation.", "danger")
        return redirect(url_for("messaging.inbox"))

    # Get all messages in conversation (in both directions)
    messages = (Message.query
                .filter(Message.product_id == product_id,
                       or_(
                           (Message.sender_id == current_user.id) & (Message.recipient_id == other_user_id),
                           (Message.sender_id == other_user_id) & (Message.recipient_id == current_user.id)
                       ))
                .order_by(Message.sent_time.asc())
                .all())

    # Mark messages as read
    for msg in messages:
        if msg.recipient_id == current_user.id:
            msg.mark_read()

    # Get other user info
    from ...models import User
    other_user = User.query.get(other_user_id)

    return render_template("messaging/conversation.html",
                          messages=messages, product=product, other_user=other_user)


@bp.route("/<int:message_id>/mark-read", methods=["POST"])
@login_required
def mark_read(message_id):
    """Mark a message as read."""
    msg = Message.query.get_or_404(message_id)

    if msg.recipient_id != current_user.id:
        flash("You don't have access to this message.", "danger")
        return redirect(url_for("messaging.inbox"))

    msg.mark_read()
    return redirect(safe_redirect_target(request.referrer) or url_for("messaging.inbox"))
