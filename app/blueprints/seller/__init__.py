from flask import Blueprint

bp = Blueprint("seller", __name__, url_prefix="/seller")

from . import routes  # noqa: E402,F401
from . import routes_cards  # noqa: E402,F401
