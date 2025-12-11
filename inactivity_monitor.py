"""
Inactivity Monitor for Fly.io Container Auto-Stop

This module implements a background greenlet that monitors container inactivity
and triggers a graceful shutdown after a configurable timeout period.

Features:
- Tracks last activity time (excluding health check endpoints)
- Uses gevent greenlet (single-worker compatible)
- Sends SIGTERM for graceful shutdown after inactivity timeout
- Logs all activity for debugging

Usage:
    from inactivity_monitor import InactivityMonitor
    monitor = InactivityMonitor(app, timeout_minutes=15)
    monitor.start()
"""

import os
import signal
import time
import logging
from typing import Optional, Set
import gevent

# Configure logging
logger = logging.getLogger(__name__)


class InactivityMonitor:
    """
    Monitors container inactivity and triggers shutdown after timeout.
    
    This class uses a gevent greenlet to periodically check if the container
    has been inactive (no real HTTP requests) for longer than the specified
    timeout. When timeout is exceeded, it sends SIGTERM to gracefully stop
    the container.
    
    Attributes:
        app: Flask application instance
        timeout_seconds: Inactivity timeout in seconds
        check_interval: How often to check for inactivity (seconds)
        excluded_paths: Set of paths that don't count as "activity"
    """
    
    def __init__(
        self,
        app,
        timeout_minutes: int = 15,
        check_interval_seconds: int = 60,
        excluded_paths: Optional[Set[str]] = None
    ):
        """
        Initialize the inactivity monitor.
        
        Args:
            app: Flask application instance
            timeout_minutes: Minutes of inactivity before shutdown (default: 15)
            check_interval_seconds: How often to check inactivity (default: 60)
            excluded_paths: Paths that don't reset the timer (default: /ping, /health)
        """
        self.app = app
        self.timeout_seconds = timeout_minutes * 60
        self.check_interval = check_interval_seconds
        self.excluded_paths = excluded_paths or {'/ping', '/health'}
        
        # Initialize last activity time to now
        self._last_activity_time: float = time.time()
        self._monitor_greenlet: Optional[gevent.Greenlet] = None
        self._is_running: bool = False
        
        # Store reference in app for access from before_request hook
        app.inactivity_monitor = self
        
        logger.info(
            f"InactivityMonitor initialized: "
            f"timeout={timeout_minutes}min, "
            f"check_interval={check_interval_seconds}s, "
            f"excluded_paths={self.excluded_paths}"
        )
    
    @property
    def last_activity_time(self) -> float:
        """Get the timestamp of last activity."""
        return self._last_activity_time
    
    @property
    def seconds_since_activity(self) -> float:
        """Get seconds elapsed since last activity."""
        return time.time() - self._last_activity_time
    
    @property
    def seconds_until_shutdown(self) -> float:
        """Get seconds remaining until shutdown (negative if overdue)."""
        return self.timeout_seconds - self.seconds_since_activity
    
    def record_activity(self, path: str) -> bool:
        """
        Record activity for a request path.
        
        Args:
            path: The request path (e.g., '/chat', '/ping')
            
        Returns:
            True if activity was recorded, False if path is excluded
        """
        if path in self.excluded_paths:
            logger.debug(f"Path '{path}' is excluded from activity tracking")
            return False
        
        old_time = self._last_activity_time
        self._last_activity_time = time.time()
        
        logger.info(
            f"Activity recorded for path '{path}'. "
            f"Timer reset. Was {time.time() - old_time:.1f}s since last activity."
        )
        return True
    
    def _monitor_loop(self):
        """
        Main monitoring loop (runs in greenlet).
        
        Periodically checks if inactivity timeout has been exceeded.
        When timeout is exceeded, triggers graceful shutdown.
        """
        logger.info(
            f"Inactivity monitor started. "
            f"Will shutdown after {self.timeout_seconds}s of inactivity."
        )
        
        while self._is_running:
            try:
                # Sleep for check interval
                gevent.sleep(self.check_interval)
                
                # Check if we should continue
                if not self._is_running:
                    break
                
                # Calculate time since last activity
                elapsed = self.seconds_since_activity
                remaining = self.seconds_until_shutdown
                
                if remaining <= 0:
                    # Timeout exceeded - trigger shutdown
                    logger.warning(
                        f"Inactivity timeout exceeded! "
                        f"No activity for {elapsed:.1f}s (timeout: {self.timeout_seconds}s). "
                        f"Initiating graceful shutdown..."
                    )
                    self._trigger_shutdown()
                    break
                else:
                    # Log status periodically
                    logger.info(
                        f"Inactivity monitor: {elapsed:.0f}s since last activity, "
                        f"{remaining:.0f}s until shutdown"
                    )
                    
            except Exception as e:
                logger.error(f"Error in inactivity monitor loop: {e}", exc_info=True)
                # Continue monitoring despite errors
                gevent.sleep(5)
    
    def _trigger_shutdown(self):
        """
        Trigger graceful shutdown of the container using Fly's Machines API.
        
        Uses Fly's Machines API to properly stop the machine.
        This ensures Fly knows it's an intentional stop, not a crash,
        so it won't auto-restart from health checks.
        
        Falls back to SIGTERM if API call fails.
        """
        import urllib.request
        import urllib.error
        
        # Get Fly environment variables
        app_name = os.environ.get('FLY_APP_NAME')
        machine_id = os.environ.get('FLY_MACHINE_ID')
        api_token = os.environ.get('FLY_API_TOKEN')
        
        logger.warning(f"Initiating container shutdown via Fly API...")
        logger.info(f"App: {app_name}, Machine: {machine_id}")
        logger.info(f"API Token present: {bool(api_token)}")
        
        if not app_name or not machine_id:
            logger.warning("Fly environment variables not found. Falling back to SIGTERM...")
            self._trigger_shutdown_fallback()
            return
        
        if not api_token:
            logger.warning("FLY_API_TOKEN not found. Falling back to SIGTERM...")
            self._trigger_shutdown_fallback()
            return
        
        try:
            # Use Fly's internal API with authentication
            api_url = f"http://_api.internal:4280/v1/apps/{app_name}/machines/{machine_id}/stop"
            
            logger.info(f"Calling Fly API: POST {api_url}")
            
            # Give a moment for logs to flush before stopping
            gevent.sleep(0.5)
            
            # Create POST request with Authorization header
            req = urllib.request.Request(api_url, method='POST')
            req.add_header('Authorization', f'Bearer {api_token}')
            
            with urllib.request.urlopen(req, timeout=10) as response:
                status_code = response.getcode()
                if status_code == 200:
                    logger.warning(f"Machine stop request successful! Container will stop shortly.")
                else:
                    response_text = response.read().decode('utf-8')
                    logger.error(f"Fly API returned status {status_code}: {response_text}")
                    logger.warning("Falling back to SIGTERM...")
                    self._trigger_shutdown_fallback()
                    
        except urllib.error.HTTPError as e:
            logger.error(f"Fly API HTTP error {e.code}: {e.reason}", exc_info=True)
            logger.warning("Falling back to SIGTERM...")
            self._trigger_shutdown_fallback()
        except Exception as e:
            logger.error(f"Failed to call Fly API: {e}", exc_info=True)
            logger.warning("Falling back to SIGTERM...")
            self._trigger_shutdown_fallback()
    
    def _trigger_shutdown_fallback(self):
        """
        Fallback shutdown method using SIGTERM.
        
        Used when Fly API is unavailable (e.g., running locally).
        """
        logger.warning("Sending SIGTERM to initiate container shutdown...")
        gevent.sleep(0.5)
        os.kill(os.getpid(), signal.SIGTERM)
    
    def start(self):
        """
        Start the inactivity monitor greenlet.
        
        This should be called once during app initialization.
        Safe to call multiple times (will not start duplicate monitors).
        """
        if self._is_running:
            logger.warning("Inactivity monitor already running")
            return
        
        self._is_running = True
        self._last_activity_time = time.time()  # Reset timer on start
        
        # Spawn the monitor greenlet
        self._monitor_greenlet = gevent.spawn(self._monitor_loop)
        
        logger.info("Inactivity monitor greenlet spawned and running")
    
    def stop(self):
        """
        Stop the inactivity monitor greenlet.
        
        This is called during app shutdown to cleanly stop the monitor.
        """
        if not self._is_running:
            return
        
        logger.info("Stopping inactivity monitor...")
        self._is_running = False
        
        if self._monitor_greenlet:
            self._monitor_greenlet.kill(block=False)
            self._monitor_greenlet = None
        
        logger.info("Inactivity monitor stopped")


def setup_activity_tracking(app):
    """
    Set up Flask before_request hook to track activity.
    
    This function registers a before_request hook that records
    activity for all requests except those to excluded paths.
    
    Args:
        app: Flask application instance (must have inactivity_monitor attribute)
    """
    from flask import request
    
    @app.before_request
    def track_request_activity():
        """Record activity for incoming requests."""
        monitor = getattr(app, 'inactivity_monitor', None)
        if monitor:
            monitor.record_activity(request.path)
    
    logger.info("Activity tracking hook registered")


def init_inactivity_monitor(app, timeout_minutes: int = 15) -> InactivityMonitor:
    """
    Initialize and start the inactivity monitor for a Flask app.
    
    This is the main entry point for setting up the inactivity monitor.
    It creates the monitor, sets up activity tracking, and starts the
    background greenlet.
    
    Args:
        app: Flask application instance
        timeout_minutes: Minutes of inactivity before shutdown (default: 15)
        
    Returns:
        The initialized InactivityMonitor instance
    """
    # Create monitor
    monitor = InactivityMonitor(app, timeout_minutes=timeout_minutes)
    
    # Set up activity tracking hook
    setup_activity_tracking(app)
    
    # Start the monitor greenlet
    monitor.start()
    
    logger.info(f"Inactivity monitor fully initialized with {timeout_minutes}min timeout")
    
    return monitor
