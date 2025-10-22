import logging
from datetime import datetime, timezone, timedelta
from flask import Blueprint, jsonify, current_app, request
from auth import token_required
from db import get_db_connection, return_db_connection
import uuid
from werkzeug.security import generate_password_hash, check_password_hash
from psycopg2.extras import RealDictCursor # realdictcursor.
import json



session_bp = Blueprint('session_bp', __name__)

@session_bp.route('/session_inc', methods=['GET'])
@token_required
def new_chat_session(current_user):
    user_id = current_user['id']
    conn = get_db_connection()
    try:
        with conn:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute("SELECT MAX(session_number) AS max_session FROM conversation_memory WHERE user_id = %s", (user_id,))
            result = cursor.fetchone()
            max_session = result['max_session'] if result and result['max_session'] is not None else 0
            new_session = max_session + 1

            cursor.execute(
                """INSERT INTO conversation_memory (user_id, session_number, last_updated) VALUES (%s, %s, %s) ON CONFLICT (user_id, session_number) DO NOTHING""",
                (user_id, new_session, datetime.now(timezone.utc).isoformat())
            )
        return jsonify({'message': 'New session started', 'session_number': new_session})
    except Exception as e:
        logging.error(f"Error creating new session for user {user_id}: {e}", exc_info=True)
        return jsonify({'error': 'Could not start a new session'}), 500
    finally:
        return_db_connection(conn)

@session_bp.route('/history/<int:session_number>', methods=['GET'])
@token_required
def get_full_session_history(current_user, session_number):
    user_id = current_user['id']
    conn = get_db_connection()
    try:
        # Get chat history with file information
        cursor = conn.cursor()
        cursor.execute(
            """SELECT ch.id, ch.original_prompt, ch.prompt, ch.response, ch.timestamp
               FROM chat_history ch
               WHERE ch.user_id = %s AND ch.session_number = %s
               ORDER BY ch.timestamp ASC""",
            (user_id, session_number)
        )
        history_rows = cursor.fetchall()

        if not history_rows:
            return jsonify({'message': 'Chat session not found or is empty'}), 404

        history = []
        for row in history_rows:
            chat_id = row['id']

            # Get files associated with this chat interaction
            cursor.execute(
                """SELECT uf.id, uf.b2_key AS stored_name, uf.original_name, uf.size,
                          uf.mime_type, uf.is_image, uf.uploaded_at
                   FROM uploaded_files uf
                   JOIN chat_files cf ON cf.file_id = uf.id
                   WHERE cf.chat_history_id = %s""",
                (chat_id,)
            )
            files = cursor.fetchall()

            # Get search_web URLs for this chat interaction
            cursor.execute(
                """SELECT call_sequence, query, urls_json, timestamp
                   FROM search_web_logs
                   WHERE chat_history_id = %s
                   ORDER BY call_sequence ASC""",
                (chat_id,)
            )
            search_logs = cursor.fetchall()

            # Parse search_web calls
            search_web_calls = []
            for log in search_logs:
                try:
                    search_web_calls.append({
                        'sequence': log['call_sequence'],
                        'query': log['query'],
                        'urls': json.loads(log['urls_json']),
                        'timestamp': log['timestamp']
                    })
                except (json.JSONDecodeError, TypeError) as e:
                    logging.warning(f"Failed to parse search_web URLs for chat_id {chat_id}: {e}")

            history.append({
                'prompt': row['original_prompt'] or row['prompt'],  # Use original if available
                'response': row['response'],
                'timestamp': row['timestamp'],
                'files': [dict(f) for f in files] if files else [],
                'search_web_calls': search_web_calls  
            })

        return jsonify(history)
    except Exception as e:
        logging.error(f"Database error fetching session history: {e}", exc_info=True)
        return jsonify({'error': 'Could not retrieve session history'}), 500
    finally:
        return_db_connection(conn)

@session_bp.route('/history', methods=['GET'])
@token_required
def get_session_history_summary(current_user):
    user_id = current_user['id']
    conn = get_db_connection()
    try:
        query = """
            SELECT
                ch.session_number,
                COALESCE(ch.original_prompt, ch.prompt) as prompt,
                ch.timestamp
            FROM (
                SELECT
                    session_number,
                    MIN(id) as first_id
                FROM chat_history
                WHERE user_id = %s
                GROUP BY session_number
            ) AS first_chats
            JOIN chat_history AS ch ON ch.id = first_chats.first_id
            ORDER BY ch.session_number DESC;
        """
        cursor = conn.cursor()
        cursor.execute(query, (user_id,))
        history_summary = cursor.fetchall()
        summary = [dict(row) for row in history_summary]
        return jsonify(summary)
    except Exception as e:
        logging.error(f"Database error fetching session history summary: {e}", exc_info=True)
        return jsonify({'error': 'Could not retrieve session history summary'}), 500
    finally:
        return_db_connection(conn)

@session_bp.route('/delete_user', methods=['DELETE'])
@token_required
def delete_user(current_user):
    user_id = current_user['id']
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM users WHERE id = %s", (user_id,))
        conn.commit()
        logging.info(f"User {user_id} and all associated data deleted successfully.")
        return jsonify({'message': 'User account and all associated data deleted successfully'}), 200
    except Exception as e:
        logging.error(f"Database error during user deletion!: {e}", exc_info=True)
        return jsonify({'message': f'Database error: {str(e)}'}), 500
    finally:
        return_db_connection(conn)


#----------------------------------------------------------------
# Conversation Sharing
#----------------------------------------------------------------

# POST /session/<session_number>/share
@session_bp.route('/session/<int:session_number>/share', methods=['POST'])
@token_required
def create_share(current_user, session_number):
    """
    Create a shareable token for the authenticated user's session.
    Request JSON can include:
      - expires_in_minutes (int) optional
      - password (string) optional (will be stored hashed)
      - is_public (bool) optional (default True)
    """
    user_id = current_user['id']
    payload = request.get_json() or {}
    expires_in = payload.get('expires_in_minutes')
    password = payload.get('password')
    is_public = 1 if payload.get('is_public', True) else 0

    share_id = str(uuid.uuid4())
    created_at = datetime.utcnow().isoformat() + "Z"
    expires_at = None
    pw_hash = None

    if expires_in:
        expires_at = (datetime.utcnow() + timedelta(minutes=int(expires_in))).isoformat() + "Z"
    if password:
        pw_hash = generate_password_hash(password)

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO conversation_shares (share_id, user_id, session_number, created_at, expires_at, password_hash, is_public, revoked) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, 0)",
            (share_id, user_id, session_number, created_at, expires_at, pw_hash, is_public)
        )
        conn.commit()
    except Exception as e:
        current_app.logger.exception("Failed to create share")
        return jsonify({"error": "Could not create share"}), 500
    finally:
        return_db_connection(conn)

    share_url = f"{current_app.config.get('FRONTEND_BASE_URL', '')}/share/{share_id}"
    return jsonify({"share_id": share_id, "share_url": share_url, "expires_at": expires_at}), 201


# GET /conversation-history/share/<share_id>
@session_bp.route('/conversation-history/share/<string:share_id>', methods=['GET'])
def get_shared_conversation(share_id):
    """
    Public endpoint to fetch conversation by share_id.
    Optional query param: password if the share is password protected.
    """
    password = request.args.get('password')
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT user_id, session_number, expires_at, password_hash, revoked, is_public "
            "FROM conversation_shares WHERE share_id = %s",
            (share_id,)
        )
        row = cursor.fetchone()
        if not row:
            return jsonify({"message": "Share not found"}), 404

        # check revoked
        if row['revoked']:
            return jsonify({"message": "This share has been revoked"}), 403

        # check expiry
        if row['expires_at']:
            expires_at = datetime.fromisoformat(row['expires_at'].replace("Z", ""))
            if datetime.utcnow() > expires_at:
                return jsonify({"message": "This share has expired"}), 410

        # check password
        pw_hash = row['password_hash']
        if pw_hash:
            if not password or not check_password_hash(pw_hash, password):
                return jsonify({"message": "Password required or incorrect"}), 401

        user_id = row['user_id']
        session_number = row['session_number']

        cursor.execute(
            """SELECT prompt, response, timestamp FROM chat_history WHERE user_id = %s AND session_number = %s ORDER BY timestamp ASC""",
            (user_id, session_number)
        )
        history_rows = cursor.fetchall()
        if not history_rows:
            return jsonify({'message': 'Chat session not found or is empty'}), 404

        history = [dict(r) for r in history_rows]
        return jsonify(history)
    except Exception as e:
        current_app.logger.exception("Error fetching shared conversation")
        return jsonify({"error": "Could not retrieve conversation"}), 500
    finally:
        return_db_connection(conn)


@session_bp.route('/search-web-urls/<int:session_number>', methods=['GET'])
@token_required
def get_search_web_urls(current_user, session_number):
    """
    Get search_web URLs during active generation (polling endpoint).
    
    This is for real-time polling while a response is being generated.
    For historical data, use /history/<session_number> which includes URLs.
    
    Query params:
        - active: Must be 'true' (this endpoint is for active polling only)
    """
    user_id = current_user['id']
    is_active = request.args.get('active', '').lower() == 'true'
    
    if not is_active:
        return jsonify({
            'error': 'This endpoint is for active polling only. Use /history/<session_number> for historical data.'
        }), 400
    
    # check cache...
    # Check cache for active generation
    cache_key = f"{user_id}-{session_number}"
    if hasattr(current_app, 'search_web_cache') and cache_key in current_app.search_web_cache:
        cached_calls = current_app.search_web_cache[cache_key]
        return jsonify({
            'active': True,
            'calls': cached_calls,
            'count': len(cached_calls)
        }), 200
    else:
        return jsonify({
            'active': True,
            'calls': [],
            'count': 0
        }), 200