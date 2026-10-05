from flask import Blueprint

bp = Blueprint('collectibles', __name__)

from . import routes
