"""
Flask-SocketIO setup for email tool WebSocket support.
Import this in app.py to initialize WebSocket.        
"""

from flask_socketio import SocketIO, join_room, emit, disconnect
from flask import request
import logging


def init_socketio(app):
    """
    Initialize Flask-SocketIO for email tool WebSocket support.

    Args:
        app: Flask application instance

    Returns:
        SocketIO instance
    """
    socketio = SocketIO(
        app,
        cors_allowed_origins="*",
        async_mode='gevent',
        logger=True,  # Enable for debugging
        engineio_logger=True,  # Enable for debugging
        ping_timeout=60,
        ping_interval=25
    )

    # WebSocket event handlers
    @socketio.on('connect')
    def handle_connect():
        """Handle client connection."""
        sid = request.sid
        logging.info(f"WebSocket client connected: sid={sid}")
        emit('connected', {'status': 'ok'})

    @socketio.on('disconnect')
    def handle_disconnect():
        """Handle client disconnection."""
        sid = request.sid
        logging.info(f"WebSocket client disconnected: sid={sid}")

    @socketio.on('email_tool_join_room')
    def handle_join_room(data):
        """
        Join user's personal email tool room.

        Expected data: {user_email (or user_id), session_id}
        """
        try:
            sid = request.sid
            logging.info(f"=== EMAIL TOOL JOIN ROOM ===")
            logging.info(f"Socket ID (sid): {sid}")
            logging.info(f"Incoming data: {data}")

            user_id = data.get('user_id')
            user_email = data.get('user_email')
            session_id = data.get('session_id')

            logging.info(f"Parsed: user_id={user_id}, user_email={user_email}, session_id={session_id}")

            # If user_email is provided but no user_id, look it up
            if user_email and not user_id:
                try:
                    from auth import get_user
                    user = get_user(user_email)
                    if user:
                        user_id = user['id']
                        logging.info(f"Resolved email {user_email} to user_id {user_id}")
                    else:
                        logging.warning(f"Could not resolve email {user_email} to a user_id")
                        emit('error', {'message': f'User not found for email: {user_email}'})
                        return
                except Exception as e:
                    logging.error(f"Error resolving user email: {e}", exc_info=True)
                    emit('error', {'message': f'Failed to resolve user: {str(e)}'})
                    return

            if not user_id or not session_id:
                logging.warning(f"Join room failed: missing params. Data: {data}") 
                emit('error', {'message': 'user_id (or valid user_email) and session_id required'})
                return

            room = f"email_tool_{user_id}_{session_id}"
            join_room(room)

            logging.info(f"SUCCESS: Client (sid={sid}) joined room: {room}")       
            emit('room_joined', {'room': room, 'user_id': user_id, 'session_id': session_id})

        except Exception as e:
            logging.error(f"CRITICAL ERROR in handle_join_room: {e}", exc_info=True)
            emit('error', {'message': f'Failed to join room: {str(e)}'})

    @socketio.on('email_tool_user_approved')
    def handle_user_approval(data):
        """
        Handle user approval for write operations.

        Expected data: {user_id, session_id, approved: true/false}
        """
        try:
            # Convert types to match agent registry key format
            user_id = int(data.get('user_id')) if data.get('user_id') else None    
            session_id = str(data.get('session_id')) if data.get('session_id') else None
            approved = data.get('approved', False)

            logging.info(f"User approval received: user={user_id}, session={session_id}, approved={approved}")

            # Get active agent from registry
            from tools.email_tool.agent import get_active_agent
            agent = get_active_agent(user_id, session_id)

            if agent:
                agent.set_approval(approved)
                emit('approval_received', {'approved': approved})
            else:
                logging.warning(f"No active agent found for user={user_id}, session={session_id}")
                emit('approval_received', {'error': 'No active email tool session'})
        except Exception as e:
            logging.error(f"Error in handle_user_approval: {e}", exc_info=True)    
            emit('error', {'message': str(e)})

    @socketio.on('email_tool_auth_completed')
    def handle_auth_completed(data):
        """
        Handle Gmail OAuth completion event.

        Expected data: {user_id, session_id, success: true/false}
        """
        try:
            # Convert types to match agent registry key format
            user_id = int(data.get('user_id')) if data.get('user_id') else None    
            session_id = str(data.get('session_id')) if data.get('session_id') else None
            success = data.get('success', True)

            logging.info(f"Gmail OAuth completed for user {user_id}, success={success}")

            # Get active agent and notify to resume
            from tools.email_tool.agent import get_active_agent
            agent = get_active_agent(user_id, session_id)

            if agent:
                agent.set_auth_completed(success)
                emit('auth_completed_ack', {'status': 'ready' if success else 'failed'})
            else:
                logging.warning(f"No active agent found for user={user_id}, session={session_id}")
                emit('auth_completed_ack', {'error': 'No active email tool session'})
        except Exception as e:
            logging.error(f"Error in handle_auth_completed: {e}", exc_info=True)   
            emit('error', {'message': str(e)})

    logging.info("Flask-SocketIO initialized for email tool")
    return socketio