import time

from flask import current_app, flash, jsonify, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required, login_user, logout_user

from ...extensions import db
from ...services import wallet_service
from ...services.mailer import send_email
from ...models import User
from ...ratelimit import client_ip, limited, limiter, too_many
from ...utils import safe_redirect_target
from . import bp
from .forms import (
    ChangePasswordForm, ForgotPasswordForm, LoginForm, ProfileForm,
    RegisterForm, ResetPasswordForm,
)
from .tokens import make_reset_token, user_from_reset_token

LOGIN_WINDOW = 900  # seconds


@bp.route("/register", methods=["GET", "POST"])
@limited("register", 10, 3600)
def register():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))
    form = RegisterForm()
    if form.validate_on_submit():
        user = User(
            name=form.name.data.strip(),
            email=form.email.data.strip().lower(),
            phone=form.phone.data.strip(),
            address=form.address.data.strip(),
            role=form.role.data,  # SelectField restricts this to buyer/seller
        )
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.commit()
        flash("Account created. Please log in.", "success")
        return redirect(url_for("auth.login"))
    return render_template("auth/register.html", form=form)


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))
    form = LoginForm()
    if form.validate_on_submit():
        email = form.email.data.strip().lower()[:255]
        ip = client_ip()
        # Three tiers of failed-attempt limits, checked BEFORE the password is looked at, so a locked-out
        # client learns nothing about whether a password was right:
        #   one client against one account (5), one client against anything (20), anyone against one account (30)
        tiers = ((f"login:{ip}:{email}", 5), (f"login:ip:{ip}", 20), (f"login:email:{email}", 30))
        wait = max(limiter().retry_after(key, limit, LOGIN_WINDOW) for key, limit in tiers)
        if wait:
            return too_many(wait, wants_json=False)
        user = User.query.filter_by(email=email).first()
        if user and user.check_password(form.password.data) and user.is_active:
            limiter().clear(tiers[0][0])
            login_user(user)
            session["login_at"] = int(time.time())  # the server ends the login after LOGIN_MAX_AGE (see security.py)
            return redirect(safe_redirect_target(request.args.get("next")) or url_for("main.dashboard"))
        for key, _ in tiers:
            limiter().hit(key, LOGIN_WINDOW)
        flash("Invalid email or password.", "danger")  # same message for all failures
    return render_template("auth/login.html", form=form)


@bp.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for("main.index"))


@bp.route("/forgot-password", methods=["GET", "POST"])
@limited("forgot", 5, 3600)
def forgot_password():
    form = ForgotPasswordForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data.strip().lower()).first()
        per_email = f"forgot-email:{form.email.data.strip().lower()[:255]}"
        if user and user.is_active and not limiter().retry_after(per_email, 3, 3600):
            limiter().hit(per_email, 3600)  # at most 3 reset emails per address per hour (same reply either way)
            link = url_for("auth.reset_password", token=make_reset_token(user), _external=True)
            body = "\n".join([
                f"Hello {user.name},",
                "",
                "Use this link to choose a new password (valid for 1 hour):",
                link,
                "",
                "If you did not ask for this, you can ignore this email; your password has not changed.",
            ])
            send_email(user.email, "[ChainBid] Reset your password", body)
        flash("If that email is registered, a reset link has been sent.", "info")
        return redirect(url_for("auth.login"))
    return render_template("auth/forgot_password.html", form=form)


@bp.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    user = user_from_reset_token(token)
    if user is None:
        flash("That reset link is invalid or has expired.", "danger")
        return redirect(url_for("auth.forgot_password"))
    form = ResetPasswordForm()
    if form.validate_on_submit():
        user.set_password(form.password.data)
        db.session.commit()
        flash("Password updated. Please log in.", "success")
        return redirect(url_for("auth.login"))
    return render_template("auth/reset_password.html", form=form)


@bp.route("/change-password", methods=["GET", "POST"])
@login_required
def change_password():
    form = ChangePasswordForm()
    if form.validate_on_submit():
        if not current_user.check_password(form.current.data):
            form.current.errors.append("Current password is incorrect.")
        else:
            current_user.set_password(form.password.data)
            db.session.commit()
            flash("Password changed.", "success")
            return redirect(url_for("auth.profile"))
    return render_template("auth/change_password.html", form=form)


@bp.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    form = ProfileForm(obj=current_user)
    if form.validate_on_submit():
        current_user.name = form.name.data.strip()
        current_user.phone = form.phone.data.strip()
        current_user.address = form.address.data.strip()
        db.session.commit()
        flash("Profile updated.", "success")
        return redirect(url_for("auth.profile"))
    return render_template("auth/profile.html", form=form)


# ---- wallet: linked only by proving control (see services/wallet_service.py) ----------------------------------------
def _json_body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


@bp.route("/wallet/challenge", methods=["POST"])
@login_required
@limited("wallet", 20, 60, by="user")
def wallet_challenge():
    try:
        message = wallet_service.start(current_user, _json_body().get("address"), request.host)
    except wallet_service.WalletError as e:
        return jsonify(ok=False, error=e.message), e.status
    return jsonify(ok=True, message=message)


@bp.route("/wallet/verify", methods=["POST"])
@login_required
@limited("wallet", 20, 60, by="user")
def wallet_verify():
    data = _json_body()
    try:
        result = wallet_service.finish(current_user, data.get("address"), data.get("signature"))
    except wallet_service.WalletError as e:
        return jsonify(ok=False, error=e.message), e.status
    note = " Your verified cards are now registered to it." if result["registered"] or result["moved"] else ""
    flash("Wallet verified: you proved you control it." + note, "success")
    return jsonify(ok=True, wallet=result["address"])


@bp.route("/wallet/remove", methods=["POST"])
@login_required
def wallet_remove():
    wallet_service.unlink(current_user)
    flash("The wallet was removed from your account.", "info")
    return redirect(url_for("auth.profile"))
