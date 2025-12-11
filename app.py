from gevent import monkey
monkey.patch_all() # Patch standard libraries for non-blocking I/O to enable Gevent-based concurrency

import logging
from flask import Flask, jsonify, render_template_string
from flask_cors import CORS
from pathlib import Path
from dotenv import load_dotenv
import datetime

# .env configuration....
env_path = Path(__file__).parent.resolve() / ".env"
load_dotenv(dotenv_path=env_path)

def create_app():
    """Create and configure an instance of the Flask application."""
    app = Flask(__name__)

    # 0. Initialize a simple in-memory cache for interruption flags and file uploads
    app.interrupt_requests = {}
    app.file_cache = {}
    app.search_web_cache = {}

    # 1. Load configuration from config.py
    app.config.from_pyfile('config.py', silent=False)

    # Set the secret key for session management
    app.secret_key = app.config['SECRET_KEY']

    # 2. Initialize logging - use stdout and force=True for gunicorn compatibility
    import sys
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        stream=sys.stdout,
        force=True
    )

    # 3. Initialize CORS
    CORS(
        app,
        resources={r"/*": {"origins": "*"}},
        supports_credentials=True,
        methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"]
    )

    # 3.5. Initialize Flask-SocketIO for email tool
    from socketio_setup import init_socketio
    socketio = init_socketio(app)
    app.socketio = socketio  # Store reference for email tool

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

    # 6. Initialize inactivity monitor for Fly.io auto-stop after 15 minutes
    # This monitors for real HTTP traffic (excludes /ping and /health)
    # and triggers graceful shutdown after 15 minutes of inactivity
    from inactivity_monitor import init_inactivity_monitor
    inactivity_monitor = init_inactivity_monitor(app, timeout_minutes=15)
    app.inactivity_monitor = inactivity_monitor
    logging.info("Inactivity monitor initialized: 15 minute timeout")

    # ---- Render-specific: Keep-alive ping endpoint ----
    @app.route('/ping', methods=['GET'])
    def ping():
        """
        Lightweight health check endpoint for Render's sleep prevention.
        Returns immediately without blocking other requests.
        """
        return jsonify({"status": "ok", "message": "Yep, breathing... barely. Stop poking me."}), 200      

    @app.route('/')
    def home():
        # Get all registered routes (except static)
        routes = [
            {
                "endpoint": rule.endpoint,
                "methods": ", ".join(sorted(rule.methods - {"HEAD", "OPTIONS"})),
                "path": str(rule)
            }
            for rule in app.url_map.iter_rules()
            if rule.endpoint != 'static'
        ]

        uptime = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

        html_template = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Backend Operational Status</title>
        <style>
            body {
                font-family: 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
                background: linear-gradient(135deg, #f5f7fa, #c3cfe2);
                margin: 0;
                padding: 0;
            }
            .container {
                max-width: 800px;
                margin: 60px auto;
                background: #fff;
                border-radius: 16px;
                box-shadow: 0 8px 25px rgba(0,0,0,0.1);
                padding: 40px;
                text-align: center;
            }
            h1 {
                color: #007BFF;
                font-size: 2rem;
                margin-bottom: 10px;
            }
            p {
                color: #555;
                margin-bottom: 30px;
            }
            @keyframes pulse {
                0% { box-shadow: 0 0 0 0 rgba(40,167,69,0.4); }
                70% { box-shadow: 0 0 0 10px rgba(40,167,69,0); }
                100% { box-shadow: 0 0 0 0 rgba(40,167,69,0); }
            }
            .status {
                display: inline-block;
                background: #28a745;
                color: white;
                padding: 6px 14px;
                border-radius: 20px;
                font-size: 0.9rem;
                font-weight: bold;
                animation: pulse 2s infinite;
            }
            table {
                width: 100%;
                border-collapse: collapse;
                margin-top: 20px;
            }
            th, td {
                border: 1px solid #eee;
                padding: 12px;
                text-align: left;
            }
            th {
                background: #007BFF;
                color: white;
            }
            tr:nth-child(even) {
                background: #f9f9f9;
            }
            .footer {
                margin-top: 30px;
                font-size: 0.9rem;
                color: #777;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Chatbot Backend</h1>
            <p><span class="status">✅ All Systems Operational</span></p>
            <p>Deployed on <strong>Render (Free Tier)</strong></p>
            <p><em>Last checked:</em> {{ uptime }}</p>

            <h2>Registered Endpoints</h2>
            <table>
                <tr>
                    <th>Endpoint</th>
                    <th>Path</th>
                    <th>Methods</th>
                </tr>
                {% for route in routes %}
                <tr>
                    <td>{{ route.endpoint }}</td>
                    <td>{{ route.path }}</td>
                    <td>{{ route.methods }}</td>
                </tr>
                {% endfor %}
            </table>

            <div class="footer">
                © {{ year }} Chatbot Backend • Flask Monitoring Page
            </div>
        </div>
    </body>
    </html>
    """

        return render_template_string(html_template, routes=routes, uptime=uptime, year=datetime.datetime.utcnow().year)

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
socketio = app.socketio  # Get socketio instanceroot