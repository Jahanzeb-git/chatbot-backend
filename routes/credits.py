# routes/credits.py
import logging
from flask import Blueprint, request, jsonify, current_app
from db import get_db_connection, return_db_connection
from auth import optional_token_required

logger = logging.getLogger(__name__)
credits_bp = Blueprint("credits", __name__, url_prefix="/api")


def _get_email_from_request():
    """Extract email from header, JSON body, or query param."""
    # header
    email = request.headers.get("X-User-Email")
    if email:
        return email.strip().lower()
    # json body
    if request.method in ("POST", "PUT", "PATCH"):
        payload = request.get_json(silent=True) or {}
        if isinstance(payload, dict) and payload.get("email"):
            return str(payload.get("email")).strip().lower()
    # query param
    q_email = request.args.get("email")
    if q_email:
        return q_email.strip().lower()
    return None


def _find_user_id_by_email(email: str):
    """Return users.id for given email or None if not found."""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT id FROM users WHERE lower(email) = %s", (email.lower(),))
    row = cur.fetchone()
    return_db_connection(conn)
    if row:
        return int(row['id'])
    return None


@credits_bp.route("/credits", methods=["GET"])
@optional_token_required
def get_credits(current_user):
    """
    Returns user's credit information including:
    - Total allotted credits (displayed as $5)
    - Used tokens
    - Remaining tokens
    - Cost breakdown

    Query params:
      - email (optional if authenticated): User email

    Returns:
    {
      "ok": true,
      "data": {
        "credits": {
          "total_credits_usd": 5.00,
          "used_credits_usd": 0.42,
          "remaining_credits_usd": 4.58,
          "credits_percentage_used": 8.4
        },
        "tokens": {
          "total_allotted_tokens": 2500000,
          "used_tokens": 42780,
          "remaining_tokens": 2457220,
          "tokens_percentage_used": 1.71
        },
        "breakdown": {
          "input_tokens_used": 5880,
          "output_tokens_used": 36900,
          "total_interactions": 178
        }
      }
    }
    """
    email = _get_email_from_request()

    # If authenticated user, use their email from token
    if current_user and not email:
        email = current_user.get('email')

    if not email:
        return jsonify({
            "ok": False,
            "error": "Missing user email (provide ?email= or X-User-Email header or authenticate)"
        }), 400

    user_id = _find_user_id_by_email(email)
    if user_id is None:
        return jsonify({
            "ok": False,
            "error": f"User with email '{email}' not found"
        }), 404

    # Get configuration values
    free_token_allotment = current_app.config['FREE_TOKEN_ALLOTMENT']
    display_multiplier = current_app.config['DISPLAY_CREDIT_MULTIPLIER']
    free_credit_usd = current_app.config['FREE_CREDIT_USD']

    # Calculate displayed credits
    total_display_credits = free_credit_usd * display_multiplier  # $1 * 5 = $5

    conn = get_db_connection()
    try:
        cursor = conn.cursor()

        # Get total token usage for this user
        cursor.execute(
            """SELECT
                SUM(input_tokens) as total_input_tokens,
                SUM(output_tokens) as total_output_tokens,
                SUM(input_tokens + output_tokens) as total_tokens,
                COUNT(*) as total_interactions
            FROM token_usage
            WHERE user_id = %s""",
            (user_id,)
        )
        usage_row = cursor.fetchone()

        input_tokens_used = int(usage_row['total_input_tokens'] or 0)
        output_tokens_used = int(usage_row['total_output_tokens'] or 0)
        total_tokens_used = int(usage_row['total_tokens'] or 0)
        total_interactions = int(usage_row['total_interactions'] or 0)

        # Calculate remaining tokens
        remaining_tokens = max(0, free_token_allotment - total_tokens_used)
        tokens_percentage_used = (total_tokens_used / free_token_allotment * 100) if free_token_allotment > 0 else 0

        # Calculate cost of used tokens (actual cost, not displayed)
        # Using average pricing for simplicity
        avg_price_per_1m = (
            current_app.config['DEFAULT_MODEL_PRICE_PER_1M_INPUT'] +
            current_app.config['DEFAULT_MODEL_PRICE_PER_1M_OUTPUT']
        ) / 2
        actual_cost_used = (total_tokens_used / 1_000_000) * avg_price_per_1m

        # Calculate displayed cost (multiply by 5)
        display_cost_used = actual_cost_used * display_multiplier
        remaining_display_credits = max(0, total_display_credits - display_cost_used)
        credits_percentage_used = (display_cost_used / total_display_credits * 100) if total_display_credits > 0 else 0

        return jsonify({
            "ok": True,
            "data": {
                "credits": {
                    "total_credits_usd": round(total_display_credits, 2),
                    "used_credits_usd": round(display_cost_used, 2),
                    "remaining_credits_usd": round(remaining_display_credits, 2),
                    "credits_percentage_used": round(credits_percentage_used, 1)
                },
                "tokens": {
                    "total_allotted_tokens": free_token_allotment,
                    "used_tokens": total_tokens_used,
                    "remaining_tokens": remaining_tokens,
                    "tokens_percentage_used": round(tokens_percentage_used, 1)
                },
                "breakdown": {
                    "input_tokens_used": input_tokens_used,
                    "output_tokens_used": output_tokens_used,
                    "total_interactions": total_interactions
                }
            }
        })

    except Exception as e:
        logger.exception(f"Credits query failed: {e}")
        return jsonify({
            "ok": False,
            "error": "Credits query failed",
            "details": str(e)
        }), 500
    finally:
        return_db_connection(conn)
