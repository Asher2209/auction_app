from flask import Blueprint

bp = Blueprint("buyer", __name__, url_prefix="/buyer")

from . import routes  # noqa: E402,F401
