from flask import Blueprint

bp = Blueprint("admin", __name__, url_prefix="/admin")

from . import routes  # noqa: E402,F401
from . import routes_verification  # noqa: E402,F401
