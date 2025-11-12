# gunicorn_config.py
import multiprocessing

bind = "0.0.0.0:10000"
workers = 2
worker_class = "gevent"
timeout = 120
keepalive = 5
graceful_timeout = 30

# Critical for streaming
worker_connections = 1000
max_requests = 1000
max_requests_jitter = 50

# Logging configuration
accesslog = "-"
errorlog = "-"
loglevel = "info"

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