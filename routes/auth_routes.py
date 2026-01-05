from flask import Blueprint, request, jsonify, current_app, session, redirect
from werkzeug.security import generate_password_hash, check_password_hash
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests
from psycopg2 import IntegrityError
from db import get_db_connection, return_db_connection
from auth import create_access_token, get_user, token_required
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
import logging
import secrets
import json
import sys
import traceback

auth_bp = Blueprint('auth_bp', __name__)

@auth_bp.route('/signup', methods=['POST'])
def signup():
    data = request.get_json()
    email = data.get('email')
    password = data.get('password')
    username = data.get('username')
    if not email or not password or not username:
        return jsonify({'message': 'Username, email, and password are required'}), 400

    hashed_password = generate_password_hash(password, method='pbkdf2:sha256')
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("INSERT INTO users (username, email, password) VALUES (%s, %s, %s)",
                       (username, email, hashed_password))
        conn.commit()
    except IntegrityError:
        return jsonify({'message': 'Email or username already registered'}), 400
    finally:
        return_db_connection(conn)

    return jsonify({'message': 'Signup successful. Please log in to continue.'}), 201

@auth_bp.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    email = data.get('email')
    password = data.get('password')
    if not email or not password:
        return jsonify({'message': 'Email and password are required'}), 400

    user = get_user(email)
    if not user or not check_password_hash(user['password'], password):
        return jsonify({'message': 'Invalid credentials'}), 401

    access_token = create_access_token(data={"sub": user['email']})
    return jsonify({
        'access_token': access_token,
        'user': {
            'email': user['email'],
            'username': user['username'],
            'profile_picture': user['profile_picture']
        }
    })

@auth_bp.route('/google-login', methods=['POST'])
def google_login():
    data = request.get_json(force=True)
    token = data.get("token")
    if not token:
        return jsonify({'message': 'Missing token'}), 400

    try:
        idinfo = id_token.verify_oauth2_token(token, google_requests.Request(), current_app.config['GOOGLE_CLIENT_ID'])
        email = idinfo.get("email")
        if not email or not idinfo.get("email_verified"):
            return jsonify({'message': 'Invalid or unverified email token'}), 400

        user = get_user(email)
        profile_picture = idinfo.get("picture")
        if user is None:
            username = idinfo.get("name", email.split("@")[0])
            conn = get_db_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("INSERT INTO users (username, email, profile_picture) VALUES (%s, %s, %s)", 
(username, email, profile_picture))
                conn.commit()
            except IntegrityError as e:
                if "username" in str(e):
                    return jsonify({'message': 'Username Already exist please login manually!'}), 409      
                else:
                    current_app.logger.error(f"IntegrityError when creating user {email}: {e}")
                    return jsonify({'message': 'Failed to create user due to database constraint violation.'}), 500
            finally:
                return_db_connection(conn)
            user = get_user(email)
            if user is None:
                return jsonify({'message': 'Failed to retrieve user after creation'}), 500
        else:
            # Update profile picture if user already exists and picture is available
            conn = get_db_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("UPDATE users SET profile_picture = %s WHERE id = %s ", (profile_picture, user['id']))
                conn.commit()
            except Exception as e:
                current_app.logger.error(f"Error updating profile picture for user {user['id']}: {e}")     
            finally:
                return_db_connection(conn)

        access_token = create_access_token(data={"sub": email})
        return jsonify({
            'access_token': access_token,
            'token_type': 'bearer',
            'user': {'email': user['email'], 'username': user['username'], 'profile_picture': profile_picture}
        }), 200

    except ValueError as e:
        return jsonify({'message': 'Invalid token', 'error': str(e)}), 400

# -------GMAIL AUTHENTICATION ROUTES-------

def _store_oauth_state(state: str, user_id: int, session_id: str):
    """Store OAuth state in database for retrieval after callback."""
    print(f"[OAUTH] Storing state: {state[:20]}... for user_id={user_id}, session_id={session_id}", file=sys.stdout, flush=True)
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        # Create table if not exists
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS gmail_oauth_states (
                state VARCHAR(200) PRIMARY KEY,
                user_id INTEGER NOT NULL,
                session_id VARCHAR(50),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # Clean up old states (older than 10 minutes)
        cursor.execute("DELETE FROM gmail_oauth_states WHERE created_at < NOW() - INTERVAL '10 minutes'")
        # Insert new state
        cursor.execute(
            "INSERT INTO gmail_oauth_states (state, user_id, session_id) VALUES (%s, %s, %s)",
            (state, user_id, session_id)
        )
        conn.commit()
        print(f"[OAUTH] State stored successfully in DB", file=sys.stdout, flush=True)
        logging.info(f"Stored OAuth state for user {user_id}, session {session_id}")
    except Exception as e:
        print(f"[OAUTH ERROR] Failed to store state: {e}", file=sys.stdout, flush=True)
        raise
    finally:
        return_db_connection(conn)

def _get_oauth_state(state: str):
    """Retrieve OAuth state from database."""
    print(f"[OAUTH] Looking up state: {state[:20] if state else 'None'}...", file=sys.stdout, flush=True)
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT user_id, session_id FROM gmail_oauth_states WHERE state = %s",
            (state,)
        )
        result = cursor.fetchone()
        if result:
            print(f"[OAUTH] State found! user_id={result['user_id']}, session_id={result['session_id']}", file=sys.stdout, flush=True)
            # Delete the used state
            cursor.execute("DELETE FROM gmail_oauth_states WHERE state = %s", (state,))
            conn.commit()
            return result['user_id'], result['session_id']
        else:
            print(f"[OAUTH ERROR] State NOT found in database!", file=sys.stdout, flush=True)
            # Show all existing states for debugging
            cursor.execute("SELECT state, user_id, created_at FROM gmail_oauth_states ORDER BY created_at DESC LIMIT 5")
            rows = cursor.fetchall()
            print(f"[OAUTH DEBUG] Existing states in DB: {len(rows)}", file=sys.stdout, flush=True)
            for row in rows:
                print(f"[OAUTH DEBUG]   - state={row['state'][:20]}..., user_id={row['user_id']}, created={row['created_at']}", file=sys.stdout, flush=True)
        return None, None
    except Exception as e:
        print(f"[OAUTH ERROR] DB error looking up state: {e}", file=sys.stdout, flush=True)
        return None, None
    finally:
        return_db_connection(conn)


@auth_bp.route('/auth/gmail/authorize')
@token_required
def gmail_authorize(current_user):
    """
    Initiate Gmail OAuth flow.
    Redirects user to Google's OAuth consent page.
    """
    print(f"[AUTHORIZE] Starting Gmail OAuth for user_id={current_user['id']}", file=sys.stdout, flush=True)
    try:
        client_id = current_app.config['GOOGLE_GMAIL_CLIENT_ID']
        client_secret = current_app.config['GOOGLE_GMAIL_CLIENT_SECRET']
        backend_url = current_app.config['BACKEND_URL']
        redirect_uri = f"{backend_url}/auth/gmail/callback"
        
        print(f"[AUTHORIZE] client_id={client_id[:20]}...", file=sys.stdout, flush=True)
        print(f"[AUTHORIZE] client_secret={'SET' if client_secret else 'NOT SET'}", file=sys.stdout, flush=True)
        print(f"[AUTHORIZE] backend_url={backend_url}", file=sys.stdout, flush=True)
        print(f"[AUTHORIZE] redirect_uri={redirect_uri}", file=sys.stdout, flush=True)
        
        # Create OAuth flow
        flow = Flow.from_client_config(
            {
                "web": {
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "redirect_uris": [redirect_uri],
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token"
                }
            },
            scopes=[
                'https://www.googleapis.com/auth/gmail.readonly',
                'https://www.googleapis.com/auth/gmail.send',
                'https://www.googleapis.com/auth/gmail.modify'
            ]
        )

        flow.redirect_uri = redirect_uri

        # Generate authorization URL with custom state
        authorization_url, state = flow.authorization_url(
            access_type='offline',
            prompt='consent'
        )

        print(f"[AUTHORIZE] Generated state={state[:20]}...", file=sys.stdout, flush=True)
        print(f"[AUTHORIZE] Authorization URL generated", file=sys.stdout, flush=True)

        # Store state in DATABASE (not session) for cross-request retrieval
        session_id = request.args.get('session_id', '')
        _store_oauth_state(state, current_user['id'], session_id)

        print(f"[AUTHORIZE] Redirecting to Google...", file=sys.stdout, flush=True)
        logging.info(f"Gmail OAuth flow started for user {current_user['id']}, state={state[:20]}...")

        return redirect(authorization_url)

    except Exception as e:
        print(f"[AUTHORIZE ERROR] {type(e).__name__}: {e}", file=sys.stdout, flush=True)
        print(f"[AUTHORIZE TRACE] {traceback.format_exc()}", file=sys.stdout, flush=True)
        logging.error(f"Gmail OAuth authorization failed: {e}", exc_info=True)
        return jsonify({"error": "Failed to initiate Gmail OAuth"}), 500


@auth_bp.route('/auth/gmail/callback')
def gmail_callback():
    """
    Handle Gmail OAuth callback.
    Exchanges authorization code for tokens and stores them.
    """
    print(f"[CALLBACK] ========== GMAIL CALLBACK STARTED ==========", file=sys.stdout, flush=True)
    print(f"[CALLBACK] Request URL: {request.url}", file=sys.stdout, flush=True)
    print(f"[CALLBACK] Request args: {dict(request.args)}", file=sys.stdout, flush=True)
    
    try:
        # Check for error from Google
        error = request.args.get('error')
        if error:
            print(f"[CALLBACK ERROR] Google returned error: {error}", file=sys.stdout, flush=True)
            return f"""
                <html><body style="font-family: Arial, sans-serif; text-align: center; padding: 50px;">
                <h2>Authentication Failed</h2>
                <p>Google Error: {error}</p>
                <p>Please close this window and try again.</p>
                </body></html>
            """, 400
        
        # Get state from URL (Google returns it)
        state = request.args.get('state')
        code = request.args.get('code')
        
        print(f"[CALLBACK] State: {state[:20] if state else 'None'}...", file=sys.stdout, flush=True)
        print(f"[CALLBACK] Code: {code[:20] if code else 'None'}...", file=sys.stdout, flush=True)

        if not state:
            print(f"[CALLBACK ERROR] No state parameter!", file=sys.stdout, flush=True)
            logging.error("No state parameter in callback")
            return """
                <html><body style="font-family: Arial, sans-serif; text-align: center; padding: 50px;">
                <h2>Authentication Failed</h2>
                <p>Missing state parameter. Please try again.</p>
                </body></html>
            """, 400

        # Retrieve user_id and session_id from DATABASE
        user_id, session_id = _get_oauth_state(state)

        if not user_id:
            print(f"[CALLBACK ERROR] State not found in database!", file=sys.stdout, flush=True)
            logging.error(f"OAuth state not found in database: {state[:20]}...")
            return """
                <html><body style="font-family: Arial, sans-serif; text-align: center; padding: 50px;">
                <h2>Authentication Failed</h2>
                <p>Session expired or invalid. Please try again.</p>
                </body></html>
            """, 400

        print(f"[CALLBACK] User ID: {user_id}, Session ID: {session_id}", file=sys.stdout, flush=True)
        logging.info(f"OAuth callback for user {user_id}, session {session_id}")

        # Get config values
        client_id = current_app.config['GOOGLE_GMAIL_CLIENT_ID']
        client_secret = current_app.config['GOOGLE_GMAIL_CLIENT_SECRET']
        backend_url = current_app.config['BACKEND_URL']
        redirect_uri = f"{backend_url}/auth/gmail/callback"
        
        print(f"[CALLBACK] redirect_uri for token exchange: {redirect_uri}", file=sys.stdout, flush=True)

        # Create OAuth flow with the state
        flow = Flow.from_client_config(
            {
                "web": {
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "redirect_uris": [redirect_uri],
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token"
                }
            },
            scopes=[
                'https://www.googleapis.com/auth/gmail.readonly',
                'https://www.googleapis.com/auth/gmail.send',
                'https://www.googleapis.com/auth/gmail.modify'
            ],
            state=state
        )

        flow.redirect_uri = redirect_uri

        # Fix: Ensure authorization_response uses HTTPS
        authorization_response = request.url
        print(f"[CALLBACK] Original authorization_response: {authorization_response[:100]}...", file=sys.stdout, flush=True)
        
        if authorization_response.startswith('http://'):
            authorization_response = authorization_response.replace('http://', 'https://', 1)
            print(f"[CALLBACK] Fixed to HTTPS: {authorization_response[:100]}...", file=sys.stdout, flush=True)

        print(f"[CALLBACK] Exchanging code for tokens...", file=sys.stdout, flush=True)

        # Exchange authorization code for tokens
        try:
            flow.fetch_token(authorization_response=authorization_response)
            print(f"[CALLBACK] Token exchange successful!", file=sys.stdout, flush=True)
        except Exception as token_error:
            print(f"[CALLBACK TOKEN ERROR] {type(token_error).__name__}: {token_error}", file=sys.stdout, flush=True)
            print(f"[CALLBACK TOKEN TRACE] {traceback.format_exc()}", file=sys.stdout, flush=True)
            raise

        credentials = flow.credentials
        print(f"[CALLBACK] Got credentials. Token: {'SET' if credentials.token else 'NOT SET'}, Refresh: {'SET' if credentials.refresh_token else 'NOT SET'}", file=sys.stdout, flush=True)

        # Get user's Gmail email address
        print(f"[CALLBACK] Fetching Gmail profile...", file=sys.stdout, flush=True)
        gmail_service = build('gmail', 'v1', credentials=credentials)
        profile = gmail_service.users().getProfile(userId='me').execute()
        email_address = profile['emailAddress']
        print(f"[CALLBACK] Gmail email: {email_address}", file=sys.stdout, flush=True)

        # Store tokens in database
        print(f"[CALLBACK] Storing tokens in database...", file=sys.stdout, flush=True)
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO user_gmail_tokens (user_id, access_token, refresh_token, token_expiry, email_address)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT(user_id) DO UPDATE SET
                    access_token = excluded.access_token,
                    refresh_token = excluded.refresh_token,
                    token_expiry = excluded.token_expiry,
                    email_address = excluded.email_address,
                    updated_at = CURRENT_TIMESTAMP
            """, (
                user_id,
                credentials.token,
                credentials.refresh_token,
                credentials.expiry.isoformat() if credentials.expiry else None,
                email_address
            ))
            conn.commit()
            print(f"[CALLBACK] Tokens stored successfully!", file=sys.stdout, flush=True)
            logging.info(f"Gmail tokens stored for user {user_id}, email: {email_address}")

        finally:
            return_db_connection(conn)

        # Notify waiting email tool agent
        if session_id:
            try:
                from tools.email_tool.agent import get_active_agent
                agent = get_active_agent(user_id, session_id)
                if agent:
                    agent.set_auth_completed(True)
                    print(f"[CALLBACK] Notified agent for user {user_id}, session {session_id}", file=sys.stdout, flush=True)
                    logging.info(f"Notified agent for user {user_id}, session {session_id}")
                else:
                    print(f"[CALLBACK] No active agent for user {user_id}, session {session_id}", file=sys.stdout, flush=True)
                    logging.info(f"No active agent for user {user_id}, session {session_id}")
            except Exception as e:
                print(f"[CALLBACK WARNING] Could not notify agent: {e}", file=sys.stdout, flush=True)
                logging.warning(f"Could not notify agent: {e}")

        print(f"[CALLBACK] ========== SUCCESS ==========", file=sys.stdout, flush=True)
        
        # Return success HTML
        return f"""
            <html><body style="font-family: Arial, sans-serif; text-align: center; padding: 50px;">
            <h2>Gmail Connected!</h2>
            <p>Connected as: {email_address}</p>
            <p>This window will close automatically...</p>
            <script>setTimeout(function(){{ window.close(); }}, 1500);</script>
            </body></html>
        """

    except Exception as e:
        print(f"[CALLBACK FATAL ERROR] {type(e).__name__}: {e}", file=sys.stdout, flush=True)
        print(f"[CALLBACK FATAL TRACE] {traceback.format_exc()}", file=sys.stdout, flush=True)
        logging.error(f"Gmail OAuth callback failed: {e}", exc_info=True)
        error_msg = str(e) if str(e) else "Unknown error occurred"
        return f"""
            <html><body style="font-family: Arial, sans-serif; text-align: center; padding: 50px;">
            <h2>Authentication Failed</h2>
            <p>Error: {error_msg}</p>
            <p>Please close this window and try again.</p>
            </body></html>
        """, 500


@auth_bp.route('/auth/gmail/status', methods=['GET'])
@token_required
def gmail_status(current_user):
    """
    Check if user has connected Gmail.
    Returns connection status and email address if connected.
    """
    try:
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT email_address, created_at FROM user_gmail_tokens WHERE user_id = %s",
                (current_user['id'],)
            )
            row = cursor.fetchone()

            if row:
                return jsonify({
                    "connected": True,
                    "email_address": row['email_address'],
                    "connected_since": row['created_at']
                }), 200
            else:
                return jsonify({
                    "connected": False
                }), 200

        finally:
            return_db_connection(conn)

    except Exception as e:
        logging.error(f"Gmail status check failed: {e}", exc_info=True)
        return jsonify({"error": "Failed to check Gmail status"}), 500


@auth_bp.route('/auth/gmail/disconnect', methods=['POST'])
@token_required
def gmail_disconnect(current_user):
    """
    Disconnect Gmail account (delete stored tokens).
    """
    try:
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM user_gmail_tokens WHERE user_id = %s",
                (current_user['id'],)
            )
            conn.commit()

            logging.info(f"Gmail disconnected for user {current_user['id']}")

            return jsonify({"success": True, "message": "Gmail disconnected"}), 200

        finally:
            return_db_connection(conn)

    except Exception as e:
        logging.error(f"Gmail disconnect failed: {e}", exc_info=True)
Error: The handle is invalid.