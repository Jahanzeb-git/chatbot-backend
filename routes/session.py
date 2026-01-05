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

            # Get email_tool data for this chat interaction
            cursor.execute(
                """SELECT query, success, total_iterations, summary, iterations_json, timestamp
                   FROM email_tool_logs
                   WHERE chat_history_id = %s""",
                (chat_id,)
            )
            email_log = cursor.fetchone()

            # Parse email_tool call
            email_tool_call = None
            if email_log:
                try:
                    email_tool_call = {
                        'query': email_log['query'],
                        'success': email_log['success'],
                        'total_iterations': email_log['total_iterations'],
                        'summary': email_log['summary'],
                        'iterations': json.loads(email_log['iterations_json']),
                        'timestamp': email_log['timestamp']
                    }
                except (json.JSONDecodeError, TypeError) as e:
                    logging.warning(f"Failed to parse email_tool data for chat_id {chat_id}: {e}")

            history.append({
                'prompt': row['original_prompt'] or row['prompt'],  # Use original if available
                'response': row['response'],
                'timestamp': row['timestamp'],
                'files': [dict(f) for f in files] if files else [],
                'search_web_calls': search_web_calls,
                'email_tool_call': email_tool_call
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


@session_bp.route('/session/<int:session_number>', methods=['DELETE'])
@token_required
def delete_session(current_user, session_number):
    """
    Delete a single chat session and all associated data.
    Deletes: conversation_memory, chat_history, uploaded files (from B2 and DB)
    """
    user_id = current_user['id']
    conn = get_db_connection()
    
    try:
        cursor = conn.cursor()
        
        # 1. Get all files associated with this session to delete from B2
        cursor.execute(
            """SELECT b2_key FROM uploaded_files 
               WHERE user_id = %s AND session_number = %s""",
            (user_id, session_number)
        )
        files_to_delete = cursor.fetchall()
        
        # 2. Delete files from B2
        if files_to_delete:
            try:
                from routes.file_routes import get_b2_client
                from flask import current_app
                
                s3_client = get_b2_client()
                for file_record in files_to_delete:
                    try:
                        s3_client.delete_object(
                            Bucket=current_app.config['B2_BUCKET_NAME'],
                            Key=file_record['b2_key']
                        )
                        logging.info(f"Deleted file from B2: {file_record['b2_key']}")
                    except Exception as e:
                        logging.warning(f"Failed to delete B2 file {file_record['b2_key']}: {e}")
            except Exception as e:
                logging.error(f"B2 cleanup error for session {session_number}: {e}", exc_info=True)
        
        # 3. Delete from database (CASCADE will handle chat_files, search_web_logs automatically)
        # Delete uploaded_files (will cascade to chat_files)
        cursor.execute(
            "DELETE FROM uploaded_files WHERE user_id = %s AND session_number = %s",
            (user_id, session_number)
        )
        
        # Delete chat_history (will cascade to search_web_logs)
        cursor.execute(
            "DELETE FROM chat_history WHERE user_id = %s AND session_number = %s",
            (user_id, session_number)
        )
        
        # Delete conversation_memory
        cursor.execute(
            "DELETE FROM conversation_memory WHERE user_id = %s AND session_number = %s",
            (user_id, session_number)
        )
        
        # Delete search_web_realtime_cache
        cursor.execute(
            "DELETE FROM search_web_realtime_cache WHERE user_id = %s AND session_number = %s",
            (user_id, session_number)
        )
        
        # Delete email_tool_realtime_cache
        cursor.execute(
            "DELETE FROM email_tool_realtime_cache WHERE user_id = %s AND session_number = %s",
            (user_id, session_number)
        )
        
        conn.commit()
        
        deleted_files = len(files_to_delete)
        logging.info(f"Deleted session {session_number} for user {user_id}. Files: {deleted_files}")
        
        return jsonify({
            'message': f'Session {session_number} deleted successfully',
            'deleted_files': deleted_files
        }), 200
        
    except Exception as e:
        conn.rollback()
        logging.error(f"Error deleting session {session_number}: {e}", exc_info=True)
        return jsonify({'error': 'Failed to delete session'}), 500
    finally:
        return_db_connection(conn)


@session_bp.route('/sessions/all', methods=['DELETE'])
@token_required
def delete_all_sessions(current_user):
    """
    Delete ALL chat sessions for the user (but keep the account).
    Deletes: all conversation_memory, chat_history, uploaded files from B2 and DB
    """
    user_id = current_user['id']
    conn = get_db_connection()
    
    try:
        cursor = conn.cursor()
        
        # 1. Get all files for this user to delete from B2
        cursor.execute(
            "SELECT b2_key FROM uploaded_files WHERE user_id = %s",
            (user_id,)
        )
        files_to_delete = cursor.fetchall()
        
        # 2. Delete files from B2
        deleted_file_count = 0
        if files_to_delete:
            try:
                from routes.file_routes import get_b2_client
                from flask import current_app
                
                s3_client = get_b2_client()
                for file_record in files_to_delete:
                    try:
                        s3_client.delete_object(
                            Bucket=current_app.config['B2_BUCKET_NAME'],
                            Key=file_record['b2_key']
                        )
                        deleted_file_count += 1
                        logging.info(f"Deleted file from B2: {file_record['b2_key']}")
                    except Exception as e:
                        logging.warning(f"Failed to delete B2 file {file_record['b2_key']}: {e}")
            except Exception as e:
                logging.error(f"B2 cleanup error for user {user_id}: {e}", exc_info=True)
        
        # 3. Delete all data from database
        # Get session count before deletion
        cursor.execute(
            "SELECT COUNT(DISTINCT session_number) as count FROM chat_history WHERE user_id = %s",
            (user_id,)
        )
        session_count_result = cursor.fetchone()
        session_count = session_count_result['count'] if session_count_result else 0
        
        # Delete uploaded_files (will cascade to chat_files)
        cursor.execute("DELETE FROM uploaded_files WHERE user_id = %s", (user_id,))
        
        # Delete chat_history (will cascade to search_web_logs)
        cursor.execute("DELETE FROM chat_history WHERE user_id = %s", (user_id,))
        
        # Delete conversation_memory
        cursor.execute("DELETE FROM conversation_memory WHERE user_id = %s", (user_id,))
        
        # Delete search_web_realtime_cache
        cursor.execute("DELETE FROM search_web_realtime_cache WHERE user_id = %s", (user_id,))
        
        # Delete email_tool_realtime_cache
        cursor.execute("DELETE FROM email_tool_realtime_cache WHERE user_id = %s", (user_id,))
        
        conn.commit()
        
        logging.info(f"Deleted all sessions for user {user_id}. Sessions: {session_count}, Files: {deleted_file_count}")
        
        return jsonify({
            'message': 'All chat sessions deleted successfully',
            'deleted_sessions': session_count,
            'deleted_files': deleted_file_count
        }), 200
        
    except Exception as e:
        conn.rollback()
        logging.error(f"Error deleting all sessions for user {user_id}: {e}", exc_info=True)
        return jsonify({'error': 'Failed to delete all sessions'}), 500
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
            expires_at_value = row['expires_at']
            if isinstance(expires_at_value, str):
                expires_at = datetime.fromisoformat(expires_at_value.replace("Z", "+00:00"))
            elif isinstance(expires_at_value, datetime):
                expires_at = expires_at_value
            else:
                expires_at = None
            
            if expires_at and datetime.utcnow() > expires_at.replace(tzinfo=None):
                return jsonify({"message": "This share has expired"}), 410

        # check password
        pw_hash = row['password_hash']
        if pw_hash:
            if not password or not check_password_hash(pw_hash, password):
                return jsonify({"message": "Password required or incorrect"}), 401

        user_id = row['user_id']
        session_number = row['session_number']

        # Get chat history with file information (same as in get_full_session_history)
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

            # Get email_tool data for this chat interaction
            cursor.execute(
                """SELECT query, success, total_iterations, summary, iterations_json, timestamp
                   FROM email_tool_logs
                   WHERE chat_history_id = %s""",
                (chat_id,)
            )
            email_log = cursor.fetchone()

            # Parse email_tool call
            email_tool_call = None
            if email_log:
                try:
                    email_tool_call = {
                        'query': email_log['query'],
                        'success': email_log['success'],
                        'total_iterations': email_log['total_iterations'],
                        'summary': email_log['summary'],
                        'iterations': json.loads(email_log['iterations_json']),
                        'timestamp': email_log['timestamp']
                    }
                except (json.JSONDecodeError, TypeError) as e:
                    logging.warning(f"Failed to parse email_tool data for chat_id {chat_id}: {e}")

            history.append({
                'prompt': row['original_prompt'] or row['prompt'],  # Use original if available
                'response': row['response'],
                'timestamp': row['timestamp'],
                'files': [dict(f) for f in files] if files else [],
                'search_web_calls': search_web_calls,
                'email_tool_call': email_tool_call
            })

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
    
    Uses database cache to ensure cross-worker consistency.
    
    Query params:
        - active: Must be 'true' (this endpoint is for active polling only)
    """
    user_id = current_user['id']
    is_active = request.args.get('active', '').lower() == 'true'
    
    if not is_active:
        return jsonify({
            'error': 'This endpoint is for active polling only. Use /history/<session_number> for historical data.'
        }), 400
    
    # Check database cache for active generation (works across workers)
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """SELECT calls_json, updated_at FROM search_web_realtime_cache 
               WHERE user_id = %s AND session_number = %s""",
            (user_id, session_number)
        )
        result = cursor.fetchone()
        
        if result:
            try:
                calls = json.loads(result['calls_json'])
                return jsonify({
                    'active': True,
                    'calls': calls,
                    'count': len(calls)
                }), 200
            except json.JSONDecodeError:
                logging.error(f"Failed to decode calls_json for session {session_number}")
                return jsonify({
                    'active': True,
                    'calls': [],
                    'count': 0
                }), 200
        else:
            return jsonify({
                'active': True,
                'calls': [],
                'count': 0
            }), 200
    except Exception as e:
        logging.error(f"Error fetching realtime cache: {e}", exc_info=True)
        return jsonify({
            'active': True,
            'calls': [],
            'count': 0,
            'error': str(e)
        }), 200
    finally:
Error: The handle is invalid.