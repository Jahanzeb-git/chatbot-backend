# gunicorn_config.py
import multiprocessing

bind = "0.0.0.0:10000"
workers = 2
worker_class = "gevent"  # better streaming...
timeout = 120
keepalive = 5
# Critical for streaming
worker_connections = 1000
max_requests = 1000
max_requests_jitter = 50

# Disable request buffering
limit_request_line = 0
limit_request_fields = 100
limit_request_field_size = 0
