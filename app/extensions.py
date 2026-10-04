from flask_login import LoginManager
from flask_mail import Mail
from flask_migrate import Migrate
from flask_socketio import SocketIO
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import CSRFProtect

db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()
csrf = CSRFProtect()
socketio = SocketIO()
mail = Mail()

login_manager.login_view = "auth.login"
login_manager.session_protection = "strong"  # a session used from a different client fingerprint is dropped
login_manager.login_message_category = "warning"
