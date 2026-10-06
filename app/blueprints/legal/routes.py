from flask import current_app, redirect, render_template, request, url_for

from ... import legal
from ...utils import safe_redirect_target
from . import bp


@bp.app_context_processor
def legal_context():
    query = request.query_string.decode("utf-8", "replace")
    here = request.path + (f"?{query}" if query else "")
    return {"cookie_choice": legal.read_cookie_choice(request.cookies), "policy_version": legal.POLICY_VERSION,
            "policy_updated": legal.LAST_UPDATED, "contact_email": current_app.config["LEGAL_CONTACT_EMAIL"],
            "here": here[:500]}


@bp.route("/privacy")
def privacy():
    return render_template("legal/privacy_policy.html")


@bp.route("/terms")
def terms():
    return render_template("legal/terms_of_service.html")


@bp.route("/refunds")
def refunds():
    return render_template("legal/refund_policy.html")


@bp.route("/cookies")
def cookies():
    return render_template("legal/cookie_policy.html")


@bp.route("/cookies/consent", methods=["POST"])
def cookie_consent():
    """Works without JavaScript: the banner and the cookie page are plain forms that post here."""
    choice = request.form.get("choice")
    target = safe_redirect_target(request.form.get("next")) or url_for("legal.cookies")
    response = redirect(target)
    if choice in legal.CONSENT_CHOICES:
        response.set_cookie(legal.CONSENT_COOKIE, f"{legal.POLICY_VERSION}:{choice}", max_age=legal.CONSENT_MAX_AGE,
                            samesite="Lax", httponly=True, secure=bool(current_app.config.get("SESSION_COOKIE_SECURE")))
    return response
