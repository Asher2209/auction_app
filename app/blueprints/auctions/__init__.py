from flask import Blueprint

bp = Blueprint("auctions", __name__, url_prefix="/auctions")

from . import routes  # noqa: E402,F401
