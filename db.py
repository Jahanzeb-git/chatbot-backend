import psycopg2
from psycopg2 import pool, sql
from psycopg2.extras import RealDictCursor
import logging
from flask import current_app, g
from contextlib import contextmanager

# Global connection pool
connection_pool = None

def init_connection_pool():
    """Initialize PostgreSQL connection pool."""
    global connection_pool
    
    if connection_pool is not None:
        logging.info("Connection pool already initialized")
        return
    
    try:
        connection_pool = psycopg2.pool.ThreadedConnectionPool(
            current_app.config['DB_POOL_MIN_CONNECTIONS'],
            current_app.config['DB_POOL_MAX_CONNECTIONS'],
            current_app.config['DATABASE_URL']
        )
        logging.info("PostgreSQL connection pool created successfully")
    except Exception as e:
        logging.error(f"Failed to create connection pool: {e}", exc_info=True)
        raise

def get_db_connection():
    """
    Get a connection from the pool.
    Returns a connection with dict cursor for easy column access.
    """
    global connection_pool
    
    if connection_pool is None:
        try: 
            from flask import current_app
            init_connection_pool()
        except Exception as e: 
            raise RuntimeError(f"Failed to auto-initialize connection pool: {e}")
    
    try:
        conn = connection_pool.getconn()
        conn.cursor_factory = RealDictCursor
        return conn
    except Exception as e:
        logging.error(f"Failed to get connection from pool: {e}", exc_info=True)
        raise

def return_db_connection(conn):
    """Return a connection to the pool."""
    global connection_pool
    
    if connection_pool is not None and conn is not None:
        connection_pool.putconn(conn)

@contextmanager
def get_db():
    """Context manager for database connections."""
    conn = get_db_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        return_db_connection(conn)

def close_connection_pool():
    """Close all connections in the pool."""
    global connection_pool
    
    if connection_pool is not None:
        connection_pool.closeall()
        connection_pool = None
        logging.info("Connection pool closed")

def init_db():
    """Initialize the database schema for PostgreSQL."""
    logging.info("Initializing PostgreSQL database with schema...")
    
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        
        # PostgreSQL schema - note the differences from SQLite:
        # - SERIAL instead of AUTOINCREMENT
        # - TIMESTAMP instead of DATETIME
        # - ON DELETE CASCADE requires proper foreign key syntax
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            username TEXT UNIQUE,
            email TEXT UNIQUE NOT NULL,
            password TEXT,
            profile_picture TEXT
        );
        
        CREATE TABLE IF NOT EXISTS api_logs (
            id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
            endpoint TEXT,
            model TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        
        CREATE TABLE IF NOT EXISTS conversation_memory (
            user_id INTEGER NOT NULL,
            session_number INTEGER NOT NULL,
            summary_json TEXT,
            history_buffer TEXT,
            last_updated TEXT NOT NULL,
            PRIMARY KEY (user_id, session_number),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        
        CREATE TABLE IF NOT EXISTS user_settings (
            user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
            system_prompt TEXT,
            temperature REAL,
            top_p REAL,
            what_we_call_you TEXT,
            theme TEXT DEFAULT 'Light',
            together_api_key TEXT
        );
        
        CREATE TABLE IF NOT EXISTS chat_history (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            session_number INTEGER NOT NULL,
            prompt TEXT NOT NULL,
            response TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            token_count INTEGER DEFAULT 0,
            original_prompt TEXT NOT NULL
        );
        
        CREATE TABLE IF NOT EXISTS unauthorized_request_counts (
            session_id TEXT PRIMARY KEY,
            request_count INTEGER DEFAULT 0
        );
        
        CREATE TABLE IF NOT EXISTS token_usage (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            model TEXT NOT NULL,
            input_tokens INTEGER NOT NULL DEFAULT 0,
            output_tokens INTEGER NOT NULL DEFAULT 0,
            raw_timestamp BIGINT NOT NULL,
            timestamp_iso TEXT NOT NULL,
            session_id TEXT,
            meta_json TEXT,
            api_key_identifier TEXT DEFAULT '_default',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        
        CREATE INDEX IF NOT EXISTS idx_token_usage_user_time 
        ON token_usage (user_id, raw_timestamp DESC);
        
        CREATE TABLE IF NOT EXISTS conversation_shares (
            share_id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            session_number INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT,
            password_hash TEXT,
            is_public INTEGER DEFAULT 1,
            revoked INTEGER DEFAULT 0,
            meta_json TEXT
        );
        
        CREATE INDEX IF NOT EXISTS idx_shares_user_session 
        ON conversation_shares (user_id, session_number);
        
        CREATE TABLE IF NOT EXISTS uploaded_files (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            session_number INTEGER NOT NULL,
            b2_key TEXT NOT NULL UNIQUE,
            original_name TEXT NOT NULL,
            size INTEGER NOT NULL,
            mime_type TEXT NOT NULL,
            is_image INTEGER DEFAULT 0,
            uploaded_at TEXT NOT NULL
        );
        
        CREATE TABLE IF NOT EXISTS chat_files (
            chat_history_id INTEGER NOT NULL REFERENCES chat_history(id) ON DELETE CASCADE,
            file_id INTEGER NOT NULL REFERENCES uploaded_files(id) ON DELETE CASCADE,
            PRIMARY KEY (chat_history_id, file_id)
        );

        CREATE TABLE IF NOT EXISTS search_web_logs (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            session_number INTEGER NOT NULL,
            chat_history_id INTEGER REFERENCES chat_history(id) ON DELETE CASCADE,
            call_sequence INTEGER NOT NULL,
            query TEXT NOT NULL,
            urls_json TEXT NOT NULL,
            timestamp TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_search_logs_chat 
        ON search_web_logs (chat_history_id);

        CREATE INDEX IF NOT EXISTS idx_search_logs_session 
        ON search_web_logs (user_id, session_number);
        
        CREATE INDEX IF NOT EXISTS idx_uploaded_files_user 
        ON uploaded_files (user_id, session_number);
        
        CREATE INDEX IF NOT EXISTS idx_chat_files_chat 
        ON chat_files (chat_history_id);
        """)
        
        conn.commit()
        logging.info("PostgreSQL database initialization complete")
        
    except Exception as e:
        conn.rollback()
        logging.error(f"Database initialization failed: {e}", exc_info=True)
        raise
    finally:
        return_db_connection(conn)

def get_unauthorized_request_count(session_id):
    """Get the unauthorized request count for a session."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT request_count FROM unauthorized_request_counts WHERE session_id = %s",
            (session_id,)
        )
        result = cursor.fetchone()
        return result['request_count'] if result else 0
    except Exception as e:
        logging.error(f"Error getting unauthorized request count: {e}", exc_info=True)
        return 0
    finally:
        return_db_connection(conn)

def increment_unauthorized_request_count(session_id):
    """Increment the unauthorized request count for a session."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO unauthorized_request_counts (session_id, request_count) 
            VALUES (%s, 1) 
            ON CONFLICT(session_id) 
            DO UPDATE SET request_count = unauthorized_request_counts.request_count + 1
            """,
            (session_id,)
        )
        conn.commit()
    except Exception as e:
        conn.rollback()
        logging.error(f"Error incrementing unauthorized request count: {e}", exc_info=True)
    finally:
        return_db_connection(conn)