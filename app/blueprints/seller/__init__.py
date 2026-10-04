from flask import Blueprint

bp = Blueprint("seller", __name__, url_prefix="/seller")

from . import routes  # noqa: E402,F401
