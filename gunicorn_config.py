# gunicorn_config.py
import multiprocessing

bind = "0.0.0.0:10000"
# IMPORTANT: Set workers=1 for Flask-SocketIO without a message queue (Redis).
# With multiple workers, WebSocket connections may end up on different workers
# than HTTP requests, causing emit() to fail reaching the correct clients.
workers = 1
worker_class = "gevent"
timeout = 120
keepalive = 5
graceful_timeout = 30

# Critical for streaming
worker_connections = 1000
max_requests = 1000
max_requests_jitter = 50

# Logging configuration - output to stdout/stderr for fly logs
accesslog = "-"
errorlog = "-"
loglevel = "info"

# CRITICAL: Configure Python's logging system via logconfig_dict
# This ensures ALL logging.info/error calls from ANY file in the application
# are properly captured and sent to stdout, which fly logs captures.
logconfig_dict = {
    'version': 1,
    'disable_existing_loggers': False,  # Don't disable existing loggers
    'formatters': {
        'standard': {
            'format': '%(asctime)s [%(levelname)s] %(name)s: %(message)s',
            'datefmt': '%Y-%m-%d %H:%M:%S',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'stream': 'ext://sys.stdout',  # Explicitly use stdout
            'formatter': 'standard',
            'level': 'DEBUG',  # Capture all levels, filter at logger level
        },
    },
    'root': {
        'level': 'INFO',
        'handlers': ['console'],
    },
    'loggers': {
        # Gunicorn's own loggers
        'gunicorn.error': {
            'level': 'INFO',
            'handlers': ['console'],
            'propagate': False,
        },
        'gunicorn.access': {
            'level': 'INFO',
            'handlers': ['console'],
            'propagate': False,
        },
        # Flask and Werkzeug
        'flask': {
            'level': 'INFO',
            'handlers': ['console'],
            'propagate': False,
        },
        'werkzeug': {
            'level': 'INFO',
            'handlers': ['console'],
            'propagate': False,
        },
        # SocketIO loggers
        'socketio': {
            'level': 'INFO',
            'handlers': ['console'],
            'propagate': False,
        },
        'engineio': {
            'level': 'WARNING',  # engineio is verbose, only show warnings+
            'handlers': ['console'],
            'propagate': False,
        },
        # Google OAuth libraries
        'google': {
            'level': 'INFO',
            'handlers': ['console'],
            'propagate': False,
        },
        'googleapiclient': {
            'level': 'INFO',
            'handlers': ['console'],
            'propagate': False,
        },
    },
}

# Disable request buffering
limit_request_line = 0
limit_request_fields = 100
limit_request_field_size = 0

# Hooks for debugging startup
def on_starting(server):
    """Called just before the master process is initialized."""
    server.log.info("Gunicorn master process starting")

def when_ready(server):
    """Called just after the server is started."""
    server.log.info("Gunicorn server is ready. Spawning workers")

def worker_int(worker):
    """Called just after a worker exited on SIGINT or SIGQUIT."""
    worker.log.info("Worker received INT or QUIT signal")

def pre_fork(server, worker):
    """Called just before a worker is forked."""
    server.log.info(f"About to fork worker {worker.pid}")

def post_fork(server, worker):
    """Called just after a worker has been forked."""
    server.log.info(f"Worker spawned with pid: {worker.pid}")