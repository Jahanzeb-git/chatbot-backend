import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# --- Configuration ---
# --- BASE DIRECTORY ---
BASE_DIR = os.path.abspath(os.path.dirname(__file__))

# --- CORE SETTINGS ---
# PostgreSQL database URL from environment
DATABASE_URL = os.getenv('DATABASE_URL')
if not DATABASE_URL:
    raise ValueError("DATABASE_URL environment variable is required")

SECRET_KEY = os.getenv('JWT_SECRET_KEY')
if not SECRET_KEY:
    raise ValueError("JWT_SECRET_KEY environment variable is required")

# ---JWT SETTING ---
ALGORITHM = 'HS256'
ACCESS_TOKEN_EXPIRE_DAYS = 180

# --- API KEYS AND SERVICE CONFIG ---
GOOGLE_CLIENT_ID = os.getenv('GOOGLE_CLIENT_ID')
TOGETHER_API_KEY = os.getenv('TOGETHER_API_KEY')
TAVILY_API_KEY = os.getenv('TAVILY_API_KEY')

# --- BACKBLAZE B2 CONFIGURATION ---
B2_KEY_ID = os.getenv('B2_KEY_ID')
B2_APP_KEY = os.getenv('B2_APP_KEY')
B2_BUCKET_NAME = os.getenv('B2_BUCKET_NAME')
B2_ENDPOINT = os.getenv('B2_ENDPOINT')

# Validate B2 credentials
if not all([B2_KEY_ID, B2_APP_KEY, B2_BUCKET_NAME, B2_ENDPOINT]):
    raise ValueError("All B2 configuration variables are required (B2_KEY_ID, B2_APP_KEY, B2_BUCKET_NAME, B2_ENDPOINT)")

# --- TOOL CONFIGURATION ---
MAX_TOOL_CALLS_PER_INTERACTION = 5

# -- LLM MODEL CONFIG ---
DEFAULT_LLM = "Qwen/Qwen3-235B-A22B-Instruct-2507-tput"
REASON_LLM = "Qwen/Qwen3-235B-A22B-Thinking-2507"
CODE_LLM = "Qwen/Qwen3-Coder-480B-A35B-Instruct-FP8"
SUMMARIZER_LLM = "meta-llama/Llama-3.3-70B-Instruct-Turbo-Free"

# --- FILE UPLOAD CONFIGURATION ---
MAX_FILES_PER_USER = 30
MAX_FILES_PER_PROMPT = 5
MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024  # 10MB

# --- TOKEN-AWARE MEMORY MANAGEMENT ---
MAX_CONTEXT_TOKENS = 10000
MIN_INTERACTIONS_BEFORE_SUMMARY = 3
MAX_INTERACTIONS_LIMIT = 50
SMOOTHING_FACTOR = 0.8
SAFETY_MARGIN = 0.9

# --- LEGACY MEMORY SETTINGS (for backward compatibility) ---
SHORT_TERM_MEMORY_K = 4

# --- CONVERSATION SUMMARY SCHEMA ---
CONVERSATION_SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {
        "interactions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "timestamp": {"type": "string", "format": "date-time"},
                    "summary": {"type": "string"},
                    "verbatim_context": {"type": "string"},
                    "priority_score": {"type": "number"}
                },
                "required": ["timestamp", "summary"]
            }
        },
        "important_details": {
            "type": "array",
            "items": {"type": "string"}
        }
    },
    "required": ["interactions", "important_details"]
}

# --- DATABASE CONNECTION POOL SETTINGS ---
DB_POOL_MIN_CONNECTIONS = 1
DB_POOL_MAX_CONNECTIONS = 10