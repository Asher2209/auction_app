from flask import Blueprint

bp = Blueprint("auctions", __name__, url_prefix="/auctions")

from . import routes  # noqa: E402,F401
# Force reload Tue Oct  6 14:28:53 IST 2026
