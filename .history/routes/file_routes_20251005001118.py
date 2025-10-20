import os
import io
import logging
import uuid
from datetime import datetime, timezone
from flask import Blueprint, request, jsonify, current_app, send_file
from werkzeug.utils import secure_filename
from auth import token_required
from db import get_db_connection

file_bp = Blueprint('file_bp', __name__)

# Graceful imports with fallbacks
try:
    import magic
    HAS_MAGIC = True
except ImportError:
    HAS_MAGIC = False
    logging.warning("python-magic not available. File type detection will be limited.")

try:
    import pypdf
    HAS_PYPDF = True
except ImportError:
    HAS_PYPDF = False
    logging.warning("pypdf not available. PDF processing will be disabled.")

try:
    import docx
    HAS_DOCX = True
except ImportError:
    HAS_DOCX = False
    logging.warning("python-docx not available. DOCX processing will be disabled.")

try:
    import openpyxl
    HAS_OPENPYXL = True
except ImportError:
    HAS_OPENPYXL = False
    logging.warning("openpyxl not available. XLSX processing will be disabled.")

# MIME type mappings
MIME_TYPE_MAP = {
    'text/plain': '.txt',
    'application/pdf': '.pdf',
    'application/msword': '.doc',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document': '.docx',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': '.xlsx',
    'text/markdown': '.md',
    'text/csv': '.csv',
    'application/json': '.json',
    'application/xml': '.xml',
    'text/html': '.html',
    'text/css': '.css',
    'application/javascript': '.js',
    'application/x-python-code': '.py',
    'text/x-python': '.py',
    'text/x-c': '.c',
    'text/x-c++src': '.cpp',
    'text/x-java-source': '.java',
    'application/x-sh': '.sh',
    'image/jpeg': '.jpeg',
    'image/png': '.png',
}

EXT_TO_MIME = {
    '.txt': 'text/plain',
    '.pdf': 'application/pdf',
    '.doc': 'application/msword',
    '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    '.md': 'text/markdown',
    '.csv': 'text/csv',
    '.json': 'application/json',
    '.xml': 'application/xml',
    '.html': 'text/html',
    '.css': 'text/css',
    '.js': 'application/javascript',
    '.py': 'text/x-python',
    '.c': 'text/x-c',
    '.cpp': 'text/x-c++src',
    '.java': 'text/x-java-source',
    '.sh': 'application/x-sh',
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.png': 'image/png',
}

def get_file_extension(mime_type):
    """Get the file extension from the MIME type."""
    return MIME_TYPE_MAP.get(mime_type)

def detect_mime_type(file_content_bytes, filename):
    """Detect MIME type with fallback methods."""
    if HAS_MAGIC:
        try:
            return magic.from_buffer(file_content_bytes, mime=True)
        except Exception as e:
            logging.warning(f"Magic detection failed: {e}")

    if filename:
        _, ext = os.path.splitext(filename.lower())
        if ext in EXT_TO_MIME:
            return EXT_TO_MIME[ext]

    try:
        file_content_bytes.decode('utf-8')
        return 'text/plain'
    except UnicodeDecodeError:
        pass

    if file_content_bytes.startswith(b'%PDF'):
        return 'application/pdf'

    if file_content_bytes.startswith(b'PK'):
        if filename:
            if filename.lower().endswith('.docx'):
                return 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
            elif filename.lower().endswith('.xlsx'):
                return 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'

    return 'application/octet-stream'

def get_user_file_count(user_id):
    """Get total number of files stored for a user."""
    conn = get_db_connection()
    try:
        result = conn.execute(
            "SELECT COUNT(*) as count FROM uploaded_files WHERE user_id = ?",
            (user_id,)
        ).fetchone()
        return result['count'] if result else 0
    finally:
        conn.close()

def get_user_upload_dir(user_id):
    """Get or create user's upload directory."""
    user_dir = os.path.join(current_app.config['UPLOAD_DIR'], str(user_id))
    os.makedirs(user_dir, exist_ok=True)
    return user_dir

@file_bp.route('/upload', methods=['POST'])
@token_required
def upload_files(current_user):
    """Upload 1-5 files for a chat session."""
    try:
        user_id = current_user['id']
        session_id = request.form.get('session_id')

        if not session_id:
            return jsonify({"error": "session_id is required"}), 400

        # Get uploaded files
        files = request.files.getlist('files')

        if not files or len(files) == 0:
            return jsonify({"error": "No files provided"}), 400

        if len(files) > current_app.config['MAX_FILES_PER_PROMPT']:
            return jsonify({
                "error": f"Maximum {current_app.config['MAX_FILES_PER_PROMPT']} files per prompt"
            }), 400

        # Check user's total file count
        current_file_count = get_user_file_count(user_id)
        if current_file_count + len(files) > current_app.config['MAX_FILES_PER_USER']:
            return jsonify({
                "error": f"File limit exceeded. You can store maximum {current_app.config['MAX_FILES_PER_USER']} files. Current: {current_file_count}"
            }), 400

        user_dir = get_user_upload_dir(user_id)
        uploaded_files_metadata = []
        total_size = 0
        file_ids = []

        conn = get_db_connection()

        try:
            for file in files:
                if not file or file.filename == '':
                    continue

                # Read file content
                file_content_bytes = file.read()
                file_size = len(file_content_bytes)

                if file_size == 0:
                    return jsonify({"error": f"File {file.filename} is empty"}), 400

                if file_size > current_app.config['MAX_FILE_SIZE_BYTES']:
                    return jsonify({
                        "error": f"File {file.filename} exceeds 10MB limit"
                    }), 400

                # Detect MIME type
                mime_type = detect_mime_type(file_content_bytes, file.filename)

                # Generate stored filename
                file_ext = get_file_extension(mime_type) or os.path.splitext(file.filename)[1] or '.bin'
                stored_name = f"{uuid.uuid4()}{file_ext}"
                file_path = os.path.join(user_dir, stored_name)

                # Save file to disk
                with open(file_path, 'wb') as f:
                    f.write(file_content_bytes)

                is_image = 1 if mime_type in ['image/jpeg', 'image/png'] else 0
                uploaded_at = datetime.now(timezone.utc).isoformat()

                # Insert into database
                cursor = conn.execute(
                    """INSERT INTO uploaded_files
                       (user_id, session_number, stored_name, original_name, size, mime_type, is_image, uploaded_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (user_id, int(session_id), stored_name, file.filename, file_size, mime_type, is_image, uploaded_at)
                )
                file_id = cursor.lastrowid
                file_ids.append(file_id)

                uploaded_files_metadata.append({
                    "stored_name": stored_name,
                    "original_name": file.filename,
                    "size": file_size,
                    "type": mime_type,
                    "is_image": bool(is_image)
                })

                total_size += file_size

            conn.commit()

            # Stage file IDs in cache for the next chat request
            cache_key = f"{user_id}-{session_id}"
            if not hasattr(current_app, 'file_cache'):
                current_app.file_cache = {}
            current_app.file_cache[cache_key] = file_ids

            return jsonify({
                "message": f"{len(uploaded_files_metadata)} file(s) staged successfully",
                "files": uploaded_files_metadata,
                "total_size": total_size
            }), 200

        except Exception as e:
            conn.rollback()
            # Cleanup uploaded files on error
            for metadata in uploaded_files_metadata:
                try:
                    os.remove(os.path.join(user_dir, metadata['stored_name']))
                except:
                    pass
            raise
        finally:
            conn.close()

    except Exception as e:
        logging.error(f"File upload error: {e}", exc_info=True)
        return jsonify({"error": f"File upload failed: {str(e)}"}), 500

@file_bp.route('/files/<session_id>/<stored_name>', methods=['GET'])
@token_required
def get_file_content(current_user, session_id, stored_name):
    """Get raw file content by stored name."""
    user_id = current_user['id']
    conn = get_db_connection()

    try:
        # Verify file belongs to user and session
        file_record = conn.execute(
            """SELECT stored_name, original_name, mime_type, is_image
               FROM uploaded_files
               WHERE user_id = ? AND session_number = ? AND stored_name = ?""",
            (user_id, int(session_id), stored_name)
        ).fetchone()

        if not file_record:
            return jsonify({"error": "File not found or access denied"}), 404

        file_path = os.path.join(get_user_upload_dir(user_id), stored_name)

        if not os.path.exists(file_path):
            return jsonify({"error": "File not found on disk"}), 404

        # For images, return as binary with proper content type
        if file_record['is_image']:
            return send_file(file_path, mimetype=file_record['mime_type'])

        # For text files, return content
        return send_file(
            file_path,
            mimetype=file_record['mime_type'],
            as_attachment=False,
            download_name=file_record['original_name']
        )

    except Exception as e:
        logging.error(f"Error retrieving file: {e}", exc_info=True)
        return jsonify({"error": "Failed to retrieve file"}), 500
    finally:
        conn.close()

@file_bp.route('/files/list', methods=['GET'])
@token_required
def list_user_files(current_user):
    """List all files for the user, optionally filtered by session."""
    user_id = current_user['id']
    session_number = request.args.get('session_number', type=int)

    conn = get_db_connection()
    try:
        if session_number:
            files = conn.execute(
                """SELECT id, stored_name, original_name, size, mime_type, is_image, uploaded_at, session_number
                   FROM uploaded_files
                   WHERE user_id = ? AND session_number = ?
                   ORDER BY uploaded_at DESC""",
                (user_id, session_number)
            ).fetchall()
        else:
            files = conn.execute(
                """SELECT id, stored_name, original_name, size, mime_type, is_image, uploaded_at, session_number
                   FROM uploaded_files
                   WHERE user_id = ?
                   ORDER BY uploaded_at DESC""",
                (user_id,)
            ).fetchall()

        files_list = [dict(file) for file in files]
        return jsonify({
            "files": files_list,
            "total": len(files_list)
        }), 200

    except Exception as e:
        logging.error(f"Error listing files: {e}", exc_info=True)
        return jsonify({"error": "Failed to list files"}), 500
    finally:
        conn.close()

@file_bp.route('/files', methods=['DELETE'])
@token_required
def delete_files(current_user):
    """Delete specific files or all files for the user."""
    user_id = current_user['id']
    data = request.json or {}

    delete_all = data.get('delete_all', False)
    stored_names = data.get('stored_names', [])

    if not delete_all and not stored_names:
        return jsonify({"error": "Provide 'stored_names' array or 'delete_all': true"}), 400

    conn = get_db_connection()
    user_dir = get_user_upload_dir(user_id)

    try:
        if delete_all:
            # Get all user's files
            files = conn.execute(
                "SELECT stored_name FROM uploaded_files WHERE user_id = ?",
                (user_id,)
            ).fetchall()

            # Delete from disk
            for file in files:
                try:
                    os.remove(os.path.join(user_dir, file['stored_name']))
                except Exception as e:
                    logging.warning(f"Failed to delete file {file['stored_name']}: {e}")

            # Delete from database
            conn.execute("DELETE FROM uploaded_files WHERE user_id = ?", (user_id,))
            conn.commit()

            return jsonify({"message": f"Deleted {len(files)} file(s)"}), 200

        else:
            # Delete specific files
            deleted_count = 0
            for stored_name in stored_names:
                # Verify ownership
                file_record = conn.execute(
                    "SELECT id FROM uploaded_files WHERE user_id = ? AND stored_name = ?",
                    (user_id, stored_name)
                ).fetchone()

                if file_record:
                    # Delete from disk
                    try:
                        os.remove(os.path.join(user_dir, stored_name))
                    except Exception as e:
                        logging.warning(f"Failed to delete file {stored_name}: {e}")

                    # Delete from database
                    conn.execute(
                        "DELETE FROM uploaded_files WHERE user_id = ? AND stored_name = ?",
                        (user_id, stored_name)
                    )
                    deleted_count += 1

            conn.commit()
            return jsonify({"message": f"Deleted {deleted_count} file(s)"}), 200

    except Exception as e:
        conn.rollback()
        logging.error(f"Error deleting files: {e}", exc_info=True)
        return jsonify({"error": "Failed to delete files"}), 500
    finally:
        conn.close()

@file_bp.route('/upload/status', methods=['GET'])
@token_required
def upload_status(current_user):
    """Check if there are staged files for the session."""
    session_id = request.args.get('session_id')
    if not session_id:
        return jsonify({"error": "session_id is required"}), 400

    user_id = current_user['id']
    cache_key = f"{user_id}-{session_id}"

    if hasattr(current_app, 'file_cache') and cache_key in current_app.file_cache:
        file_ids = current_app.file_cache[cache_key]

        # Get metadata for staged files
        conn = get_db_connection()
        try:
            placeholders = ','.join('?' * len(file_ids))
            files = conn.execute(
                f"""SELECT stored_name, original_name, size, mime_type
                   FROM uploaded_files
                   WHERE id IN ({placeholders})""",
                file_ids
            ).fetchall()

            return jsonify({
                "has_files": True,
                "files": [dict(f) for f in files],
                "count": len(files)
            }), 200
        finally:
            conn.close()

    return jsonify({"has_files": False, "count": 0}), 200

@file_bp.route('/upload/clear', methods=['POST'])
@token_required
def clear_upload(current_user):
    """Clear staged files for the session."""
    data = request.json or {}
    session_id = data.get('session_id')
    if not session_id:
        return jsonify({"error": "session_id is required"}), 400

    user_id = current_user['id']
    cache_key = f"{user_id}-{session_id}"

    if hasattr(current_app, 'file_cache') and cache_key in current_app.file_cache:
        del current_app.file_cache[cache_key]
        return jsonify({"message": "Staged files cleared successfully"}), 200

    return jsonify({"message": "No files to clear"}), 200