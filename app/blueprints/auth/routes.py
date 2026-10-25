import secrets
import time

from flask import abort, flash, jsonify, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required, login_user, logout_user

from ... import legal
from ...extensions import db
from ...services import google_login
from ...services import sessions as user_sessions
from ...services import two_factor as tf
from ...services import wallet_service
from ...services.mailer import send_email
from ...models import User, utcnow
from ...ratelimit import client_ip, limited, limiter, too_many
from ...utils import safe_redirect_target
from . import bp
from .forms import (
    ChangePasswordForm, ForgotPasswordForm, GoogleSignupForm, LoginForm, ProfileForm,
    RegisterForm, ResetPasswordForm, TwoFactorForm, TwoFactorManageForm, TwoFactorSetupForm,
)
from .tokens import make_email_token, make_reset_token, user_from_email_token, user_from_reset_token

LOGIN_WINDOW = 900  # seconds
PENDING = "2fa_pending"  # session key: a password-checked sign-in waiting for its second step
PENDING_MAX_AGE = 300  # seconds to type the code before the password has to be entered again


def _start_session(user):
    login_user(user)
    session["login_at"] = int(time.time())  # the server ends the login after LOGIN_MAX_AGE (see security.py)
    user_sessions.start(user)  # this browser's row on the signed-in devices page


def _first_factor_passed(user, target):
    """The password, a wallet or Google has vouched for `user`: sign in, or ask for the second step first.
    Returns where to go next."""
    if user.two_factor_enabled:
        session[PENDING] = {"id": user.id, "at": int(time.time()), "next": target}
        return url_for("auth.two_factor")
    _start_session(user)
    return target or url_for("main.dashboard")


def _end_other_sessions():
    """After a password or two-step change: every other signed-in browser has to sign in again."""
    return user_sessions.revoke_others(current_user, keep=session.get(user_sessions.KEY))


def send_verification(user):
    link = url_for("auth.verify_email", token=make_email_token(user), _external=True)
    body = "\n".join([
        f"Hello {user.name},",
        "",
        "Confirm that this is your email address to start bidding and selling on MintLot (the link works for 3 days):",
        link,
        "",
        "If you did not create a MintLot account, you can ignore this email.",
    ])
    send_email(user.email, "[MintLot] Confirm your email address", body)


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
            role="member",  # every account can both buy and sell; admins are made by hand
            consent_version=legal.POLICY_VERSION,  # which policies they agreed to, and when
            consented_at=utcnow(),
        )
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.commit()
        send_verification(user)
        _start_session(user)
        flash(f"Welcome to MintLot. We sent a confirmation link to {user.email}: open it to start bidding and selling.", "success")
        return redirect(url_for("main.dashboard"))
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
            return redirect(_first_factor_passed(user, safe_redirect_target(request.args.get("next"))))
        for key, _ in tiers:
            limiter().hit(key, LOGIN_WINDOW)
        flash("Invalid email or password.", "danger")  # same message for all failures
    return render_template("auth/login.html", form=form)


# ---- two-step sign-in (see services/two_factor.py) ------------------------------------------------------------------
def _pending_user():
    pending = session.get(PENDING)
    if not isinstance(pending, dict) or int(time.time()) - int(pending.get("at", 0)) > PENDING_MAX_AGE:
        session.pop(PENDING, None)
        return None, None
    user = db.session.get(User, pending.get("id"))
    if user is None or not user.is_active or not user.two_factor_enabled:
        session.pop(PENDING, None)
        return None, None
    return user, pending.get("next")


@bp.route("/two-factor", methods=["GET", "POST"])
@limited("2fa", 10, LOGIN_WINDOW)
def two_factor():
    user, target = _pending_user()
    if user is None:
        flash("Please log in again.", "warning")
        return redirect(url_for("auth.login"))
    form = TwoFactorForm()
    if form.validate_on_submit():
        key = f"2fa:user:{user.id}"  # five wrong codes for one account, from anywhere, and it waits
        wait = limiter().retry_after(key, 5, LOGIN_WINDOW)
        if wait:
            return too_many(wait, wants_json=False)
        if tf.check(user, form.code.data):
            db.session.commit()
            limiter().clear(key)
            session.pop(PENDING, None)
            _start_session(user)
            if tf.recovery_left(user) <= 2:
                flash(f"You have {tf.recovery_left(user)} recovery codes left. Make new ones from your account page.", "warning")
            return redirect(target or url_for("main.dashboard"))
        limiter().hit(key, LOGIN_WINDOW)
        form.code.errors.append("That code is not right. Check your authenticator app and try again.")
    return render_template("auth/two_factor.html", form=form)


@bp.route("/two-factor/setup", methods=["GET", "POST"])
@login_required
@limited("2fa-setup", 10, LOGIN_WINDOW, by="user")
def two_factor_setup():
    if current_user.two_factor_enabled:
        return redirect(url_for("auth.profile"))
    secret = session.get("totp_setup") or tf.new_secret()  # kept in the session until a code proves it
    session["totp_setup"] = secret
    form = TwoFactorSetupForm()
    if form.validate_on_submit():
        step = tf.matching_step(secret, form.code.data)
        if step is not None:
            codes = tf.enable(current_user, secret, step)
            db.session.commit()
            _end_other_sessions()
            session.pop("totp_setup", None)
            flash("Two-step sign-in is on. Keep these recovery codes somewhere safe.", "success")
            return render_template("auth/recovery_codes.html", codes=codes)
        form.code.errors.append("That code is not right. Check the time on your phone and try the newest code.")
    uri = tf.provisioning_uri(secret, current_user.email)
    return render_template("auth/two_factor_setup.html", form=form, secret=secret, qr=tf.qr_svg(uri))


def _manage_form_checks(form):
    """Both factors again before anything that weakens or replaces them."""
    if not current_user.check_password(form.password.data):
        form.password.errors.append("Password is incorrect.")
        return False
    if not tf.check(current_user, form.code.data):
        form.code.errors.append("That code is not right.")
        return False
    return True


@bp.route("/two-factor/manage", methods=["GET", "POST"])
@login_required
@limited("2fa-manage", 10, LOGIN_WINDOW, by="user")
def two_factor_manage():
    if not current_user.two_factor_enabled:
        return redirect(url_for("auth.two_factor_setup"))
    form = TwoFactorManageForm()
    action = request.form.get("action")
    if form.validate_on_submit() and action in ("disable", "regenerate") and _manage_form_checks(form):
        if action == "disable":
            tf.disable(current_user)
            db.session.commit()
            _end_other_sessions()
            flash("Two-step sign-in is off. Your account is protected by your password only.", "warning")
            return redirect(url_for("auth.profile"))
        codes = tf.regenerate_recovery_codes(current_user)
        db.session.commit()
        flash("New recovery codes made. The old ones no longer work.", "success")
        return render_template("auth/recovery_codes.html", codes=codes)
    return render_template("auth/two_factor_manage.html", form=form, left=tf.recovery_left(current_user))


# ---- signed-in devices (see services/sessions.py) -------------------------------------------------------------------
@bp.route("/sessions")
@login_required
def sessions_page():
    rows = user_sessions.active(current_user)
    return render_template("auth/sessions.html", rows=rows, here=session.get(user_sessions.KEY), label=user_sessions.device_label)


@bp.route("/sessions/<sid>/end", methods=["POST"])
@login_required
def end_session(sid):
    if sid == session.get(user_sessions.KEY):
        return redirect(url_for("auth.sessions_page"))  # this device signs out with the Logout button
    if user_sessions.revoke(current_user, sid):
        flash("That device has been signed out.", "success")
    return redirect(url_for("auth.sessions_page"))


@bp.route("/sessions/end-others", methods=["POST"])
@login_required
def end_other_sessions():
    ended = _end_other_sessions()
    flash(f"Signed out of {ended} other device{'' if ended == 1 else 's'}." if ended else "No other devices were signed in.", "success")
    return redirect(url_for("auth.sessions_page"))


@bp.route("/verify-email/<token>")
def verify_email(token):
    user = user_from_email_token(token)
    if user is None:
        flash("That confirmation link is invalid or has expired. Log in to have a new one sent.", "danger")
        return redirect(url_for("auth.login"))
    if not user.email_verified:
        user.email_verified_at = utcnow()
        db.session.commit()
    flash("Email address confirmed. You can now bid and sell.", "success")
    return redirect(url_for("main.dashboard") if current_user.is_authenticated else url_for("auth.login"))


@bp.route("/verify-email/resend", methods=["POST"])
@login_required
@limited("verify-resend", 3, 3600, by="user")
def resend_verification():
    if current_user.email_verified:
        flash("Your email address is already confirmed.", "info")
    else:
        send_verification(current_user)
        flash(f"A new confirmation link is on its way to {current_user.email}.", "info")
    return redirect(safe_redirect_target(request.form.get("next")) or url_for("main.dashboard"))


@bp.route("/logout", methods=["POST"])
@login_required
def logout():
    user_sessions.end_current()
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
            send_email(user.email, "[MintLot] Reset your password", body)
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
        user_sessions.revoke_others(user)  # whoever knew the old password is signed out everywhere
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
            ended = _end_other_sessions()
            flash("Password changed." + (f" {ended} other signed-in device{'' if ended == 1 else 's'} signed out." if ended else ""), "success")
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


@bp.route("/wallet-login/challenge", methods=["POST"])
@limited("wallet-login", 20, 60)
def wallet_login_challenge():
    if current_user.is_authenticated:
        return jsonify(ok=False, error="You are already logged in."), 400
    try:
        message = wallet_service.start_login(_json_body().get("address"), request.host, request.url_root)
    except wallet_service.WalletError as e:
        return jsonify(ok=False, error=e.message), e.status
    return jsonify(ok=True, message=message)


@bp.route("/wallet-login/verify", methods=["POST"])
@limited("wallet-login", 20, 60)
def wallet_login_verify():
    data = _json_body()
    try:
        user = wallet_service.finish_login(data.get("address"), data.get("signature"))
    except wallet_service.WalletError as e:
        return jsonify(ok=False, error=e.message), e.status
    # a wallet replaces the password, not the second step
    return jsonify(ok=True, redirect=_first_factor_passed(user, safe_redirect_target(data.get("next"))))


# ---- sign in with Google (see services/google_login.py) ------------------------------------------------------------
GOOGLE_SIGNUP = "google_signup"  # session key: a Google identity with no account yet, while its owner finishes signing up


def _google_or_404():
    if not google_login.enabled():
        abort(404)


@bp.route("/google")
@limited("google", 20, 60, methods=("GET",))
def google_start():
    _google_or_404()
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))
    session["google_next"] = safe_redirect_target(request.args.get("next"))
    return google_login.client().authorize_redirect(url_for("auth.google_callback", _external=True))


@bp.route("/google/callback")
@limited("google", 20, 60, methods=("GET",))
def google_callback():
    _google_or_404()
    target = session.pop("google_next", None)
    try:
        info = google_login.profile(google_login.client().authorize_access_token())
    except google_login.OAuthError:
        flash("Google sign-in did not finish. Please try again.", "danger")
        return redirect(url_for("auth.login"))
    if not info["sub"] or not info["email"] or not info["email_verified"]:
        flash("Google did not confirm an email address for that account, so it cannot be used here.", "danger")
        return redirect(url_for("auth.login"))

    user = User.query.filter_by(google_sub=info["sub"]).first()
    if user is None:
        user = User.query.filter_by(email=info["email"]).first()
        if user is not None and not user.email_verified:
            flash(f"An account for {info['email']} exists but its email address is not confirmed yet. Open the link we "
                  "emailed when it was created (or log in and send a new one), then sign in with Google.", "warning")
            return redirect(url_for("auth.login"))
        if user is not None:
            user.google_sub = info["sub"]
            db.session.commit()
    if user is None:
        session[GOOGLE_SIGNUP] = {**info, "at": int(time.time()), "next": target}
        return redirect(url_for("auth.google_finish"))
    if not user.is_active:
        flash("This account has been deactivated.", "danger")
        return redirect(url_for("auth.login"))
    return redirect(_first_factor_passed(user, target))


@bp.route("/google/finish", methods=["GET", "POST"])
@limited("register", 10, 3600)
def google_finish():
    pending = session.get(GOOGLE_SIGNUP)
    if not isinstance(pending, dict) or int(time.time()) - int(pending.get("at", 0)) > 1800:
        session.pop(GOOGLE_SIGNUP, None)
        return redirect(url_for("auth.login"))
    form = GoogleSignupForm(data={"name": pending["name"]} if request.method == "GET" else None)
    if form.validate_on_submit():
        if User.query.filter((User.email == pending["email"]) | (User.google_sub == pending["sub"])).first():
            session.pop(GOOGLE_SIGNUP, None)  # made meanwhile in another tab: sign in with Google again to use it
            flash("An account for this Google sign-in already exists. Sign in with Google again.", "info")
            return redirect(url_for("auth.login"))
        user = User(name=form.name.data.strip(), email=pending["email"], phone=form.phone.data.strip(),
                    address=form.address.data.strip(), role="member", google_sub=pending["sub"],
                    email_verified_at=utcnow(),  # Google has confirmed the address
                    consent_version=legal.POLICY_VERSION, consented_at=utcnow())
        user.set_password(secrets.token_urlsafe(32))  # no password of its own until the owner sets one with "Forgot password"
        db.session.add(user)
        db.session.commit()
        session.pop(GOOGLE_SIGNUP, None)
        _start_session(user)
        flash("Welcome to MintLot.", "success")
        return redirect(pending.get("next") or url_for("main.dashboard"))
    return render_template("auth/google_finish.html", form=form, email=pending["email"])


@bp.route("/wallet/remove", methods=["POST"])
@login_required
def wallet_remove():
    wallet_service.unlink(current_user)
    flash("The wallet was removed from your account.", "info")
    return redirect(url_for("auth.profile"))
