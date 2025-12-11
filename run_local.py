"""
Local development server runner for the chatbot backend.
This file runs the Flask-SocketIO application in development mode with enhanced logging.

Usage: python run_local.py
"""

import os
import sys
import logging

# Set up comprehensive logging BEFORE importing the app
logging.basicConfig(
    level=logging.DEBUG,  # DEBUG level for maximum verbosity
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),  # Output to console
    ]
)

# Also configure specific loggers
logging.getLogger('flask').setLevel(logging.DEBUG)
logging.getLogger('flask_socketio').setLevel(logging.DEBUG)
logging.getLogger('engineio').setLevel(logging.DEBUG)
logging.getLogger('socketio').setLevel(logging.DEBUG)
logging.getLogger('werkzeug').setLevel(logging.DEBUG)
logging.getLogger('google').setLevel(logging.DEBUG)
logging.getLogger('google.auth').setLevel(logging.DEBUG)
logging.getLogger('googleapiclient').setLevel(logging.DEBUG)

# Reduce noise from some verbose libraries
logging.getLogger('urllib3').setLevel(logging.WARNING)

print("=" * 60)
print("STARTING LOCAL DEVELOPMENT SERVER")
print("=" * 60)

# Import the app after logging is configured
from app import app, socketio

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    host = os.environ.get('HOST', '0.0.0.0')
    
    print(f"\n🚀 Server starting on http://{host}:{port}")
    print(f"📧 Gmail OAuth callback URL: http://localhost:{port}/auth/gmail/callback")
    print(f"🔧 Debug mode: ON")
    print(f"📝 All logs will be shown in this console")
    print("=" * 60 + "\n")
    
    # Run with Flask-SocketIO's development server
    socketio.run(
        app,
        host=host,
        port=port,
        debug=True,
        use_reloader=True,
        log_output=True
    )
