from app import create_app
from app.extensions import socketio

app = create_app()

if __name__ == "__main__":
    # Use this (not `flask run`): it serves WebSockets and starts the auction scheduler.
    socketio.run(app, debug=True, allow_unsafe_werkzeug=True)
