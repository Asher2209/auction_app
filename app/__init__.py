import os

from dotenv import load_dotenv
from flask import Flask, render_template
from flask_login import current_user

load_dotenv()

from .config import Config  # noqa: E402
from .extensions import csrf, db, login_manager, mail, migrate, socketio  # noqa: E402


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    if app.config["ALLOW_TEST_EMAILS"]:
        import email_validator
        email_validator.TEST_ENVIRONMENT = True

    # Handlers must be declared before init_app so every app instance (not just the first) gets them.
    from . import sockets

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    csrf.init_app(app)
    mail.init_app(app)
    socketio.init_app(app, async_mode="threading")

    from . import models  # noqa: F401  (register models for migrations)
    from .models import utcnow
    from .blueprints.admin import bp as admin_bp
    from .blueprints.auctions import bp as auctions_bp
    from .blueprints.auth import bp as auth_bp
    from .blueprints.buyer import bp as buyer_bp
    from .blueprints.invoices import bp as invoices_bp
    from .blueprints.legal import bp as legal_bp
    from .blueprints.main import bp as main_bp
    from .blueprints.messaging import bp as messaging_bp
    from .blueprints.notifications import bp as notifications_bp
    from .blueprints.payments import bp as payments_bp
    from .blueprints.reviews import bp as reviews_bp
    from .blueprints.seller import bp as seller_bp
    from .blueprints.collectibles import bp as collectibles_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(seller_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(auctions_bp)
    app.register_blueprint(buyer_bp)
    app.register_blueprint(notifications_bp)
    app.register_blueprint(messaging_bp)
    app.register_blueprint(payments_bp)
    app.register_blueprint(invoices_bp)
    app.register_blueprint(legal_bp)
    app.register_blueprint(reviews_bp)
    app.register_blueprint(collectibles_bp)

    from .security import init_security
    init_security(app)  # before anything is started: an unsafe production config must stop the app here

    if app.config["LOCAL_CHAIN"]:
        from .services import blockchain_service
        blockchain_service.init_local_chain(app)  # development only: refuses to run alongside a real RPC_URL
        from .blueprints.devwallet import bp as devwallet_bp
        app.register_blueprint(devwallet_bp)

    if app.config["ENABLE_SCHEDULER"] and (not app.debug or os.environ.get("WERKZEUG_RUN_MAIN") == "true"):
        sockets.start_scheduler(app)  # under the debug reloader only the child process runs it

    @app.errorhandler(403)
    def forbidden(_e):
        return render_template("error.html", code=403, message="You don't have permission to view this page."), 403

    @app.errorhandler(404)
    def not_found(_e):
        return render_template("error.html", code=404, message="Page not found."), 404

    @app.errorhandler(413)
    def too_large(_e):
        return render_template("error.html", code=413, message="Upload too large (max 5 MB per image, 25 MB per request)."), 413

    @app.context_processor
    def inject_globals():
        def unread_count():
            from .models import Notification
            return Notification.query.filter_by(user_id=current_user.id, is_read=False).count()

        return {"currency": app.config["CURRENCY_SYMBOL"], "unread_count": unread_count}

    @app.template_filter("money")
    def money(value):
        return f"{app.config['CURRENCY_SYMBOL']}{value:,.2f}"

    @app.template_filter("time_left")
    def time_left(end):
        secs = int((end - utcnow()).total_seconds())
        if secs <= 0:
            return "Ended"
        d, rem = divmod(secs, 86400)
        h, rem = divmod(rem, 3600)
        m = rem // 60
        return f"{d}d {h}h" if d else f"{h}h {m}m" if h else f"{m}m"

    @app.template_filter("stars")
    def stars(value):
        full = max(0, min(5, int(round(float(value)))))  # the number shown next to the stars carries the precision
        return chr(0x2605) * full + chr(0x2606) * (5 - full)

    @app.template_filter("mask")
    def mask(name):
        return (name[:1] + "***") if name else "***"

    from . import timeutil

    @app.template_filter("local")
    def local(value):
        return timeutil.fmt(value)  # "04 Oct 2026 13:00 IST": stored UTC, shown in the site zone

    @app.template_filter("datetimeformat")
    def datetimeformat(value, fmt="%d %b %Y"):
        return timeutil.to_local(value).strftime(fmt) if value else ""

    @app.template_filter("date")
    def date_filter(value, fmt="%d %b %Y"):
        return timeutil.to_local(value).strftime(fmt) if value else ""

    @app.context_processor
    def inject_zone():
        return {"tz_name": timeutil.tz_name(), "tz_offset": app.config["TZ_OFFSET_MINUTES"]}

    return app
