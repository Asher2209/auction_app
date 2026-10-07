from flask import Blueprint

bp = Blueprint('collectibles', __name__, url_prefix='/collectibles')

from . import routes
