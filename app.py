import logging
from flask import Flask, jsonify
from flask_cors import CORS
from pathlib import Path
from dotenv import load_dotenv

# .env configuration....
env_path = Path(__file__).parent.resolve() / ".env"
load_dotenv(dotenv_path=env_path)

def create_app():
    """Create and configure an instance of the Flask application."""
    app = Flask(__name__)

    # 0. Initialize a simple in-memory cache for interruption flags and file uploads
    app.interrupt_requests = {}
    app.file_cache = {}

    # 1. Load configuration from config.py
    app.config.from_pyfile('config.py', silent=False)

    # Set the secret key for session management
    app.secret_key = app.config['SECRET_KEY']

    # 2. Initialize logging
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

    # 3. Initialize CORS
    CORS(
        app,
        resources={r"/*": {"origins": "*"}},
        supports_credentials=True,
        methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"]
    )

    # 4. Initialize the database within the app context
    with app.app_context():
        import db
        db.init_connection_pool()
        db.init_db()

    # 5. Register blueprints (your routes)
    from routes.auth_routes import auth_bp
    from routes.chat import chat_bp
    from routes.session import session_bp
    from routes.settings_routes import settings_bp
    from routes.file_routes import file_bp
    from routes.analytics import analytics_bp
    from routes.together_key_routes import user_key_bp


    app.register_blueprint(auth_bp)
    app.register_blueprint(chat_bp)
    app.register_blueprint(session_bp)
    app.register_blueprint(settings_bp)
    app.register_blueprint(file_bp)
    app.register_blueprint(analytics_bp)
    app.register_blueprint(user_key_bp)

    # ---- Render-specific: Keep-alive ping endpoint ----
    @app.route('/ping', methods=['GET'])
    def ping():
        """
        Lightweight health check endpoint for Render's sleep prevention.
        Returns immediately without blocking other requests.
        """
        return jsonify({"status": "ok", "message": "Yep, breathing... barely. Stop poking me."}), 200

    # ---- Cleanup on shutdown ----
    @app.teardown_appcontext
    def close_db_pool(error):
        """Close database connection pool on app shutdown."""
        if error:
            logging.error(f"Application error: {error}")
        import db
        db.close_connection_pool()

    logging.info("Application factory setup complete.")
    return app  # NOW return after defining routes


# This part is for running locally with `python app.py`
# For production, you would point your WSGI server to the `app` object.
app = create_app()