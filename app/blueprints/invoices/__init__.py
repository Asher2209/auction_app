from flask import Blueprint

bp = Blueprint("invoices", __name__)

from . import routes  # noqa: E402,F401
