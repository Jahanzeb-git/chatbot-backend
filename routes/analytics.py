
# routes/analytics.py
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from flask import Blueprint, request, jsonify
from db import get_db_connection, return_db_connection

logger = logging.getLogger(__name__)
analytics_bp = Blueprint("analytics", __name__, url_prefix="/api")


def _get_email_from_request() -> Optional[str]:
    """
    Prefer header 'X-User-Email' then JSON body 'email' then query param 'email'.
    Returns None if not found.
    """
    # header
    email = request.headers.get("X-User-Email")
    if email:
        return email.strip().lower()
    # json body (may not exist for GET)
    if request.method in ("POST", "PUT", "PATCH"):
        payload = request.get_json(silent=True) or {}
        if isinstance(payload, dict) and payload.get("email"):
            return str(payload.get("email")).strip().lower()
    # fallback to query param
    q_email = request.args.get("email")
    if q_email:
        return q_email.strip().lower()
    return None


def _find_user_id_by_email(email: str) -> Optional[int]:
    """Return users.id for given email or None if not found."""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT id FROM users WHERE lower(email) = %s", (email.lower(),))
    row = cur.fetchone()
    return_db_connection(conn)
    if row:
        return int(row['id'])
    return None


@analytics_bp.route("/analytics", methods=["GET"])
def get_analytics():
    """
    Returns token usage analytics for frontend visualization.

    Query params:
      - email (required): User email
      - period (optional): '7d', '30d', '90d', 'all' (default: '30d')
      - group_by (optional): 'day', 'week', 'month' (default: 'day')

    Returns:
    {
      "ok": true,
      "data": {
        "timeseries": [
          {
            "date": "2024-01-15",
            "input_tokens": 1500,
            "output_tokens": 800,
            "total_tokens": 2300
          },
          ...
        ],
        "summary": {
          "total_input_tokens": 45000,
          "total_output_tokens": 23000,
          "total_tokens": 68000,
          "total_interactions": 150
        }
      }
    }
    """
    email = _get_email_from_request()
    if not email:
        return jsonify({"ok": False, "error": "Missing user email (provide ?email= or X-User-Email header)"}), 400

    user_id = _find_user_id_by_email(email)
    if user_id is None:
        return jsonify({"ok": False, "error": f"User with email '{email}' not found"}), 404

    period = request.args.get("period", default="30d", type=str)
    group_by = request.args.get("group_by", default="day", type=str)

    # Calculate since timestamp based on period
    now = datetime.now(timezone.utc)
    if period == "7d":
        since = now - timedelta(days=7)
    elif period == "30d":
        since = now - timedelta(days=30)
    elif period == "90d":
        since = now - timedelta(days=90)
    elif period == "all":
        since = datetime(2020, 1, 1, tzinfo=timezone.utc)  # Arbitrary old date
    else:
        since = now - timedelta(days=30)  # Default to 30d

    since_ms = int(since.timestamp() * 1000)

    # Determine SQL date grouping
    if group_by == "week":
        date_trunc = "DATE_TRUNC('week', TO_TIMESTAMP(raw_timestamp / 1000.0))"
    elif group_by == "month":
        date_trunc = "DATE_TRUNC('month', TO_TIMESTAMP(raw_timestamp / 1000.0))"
    else:  # day
        date_trunc = "DATE_TRUNC('day', TO_TIMESTAMP(raw_timestamp / 1000.0))"

    conn = get_db_connection()
    cur = conn.cursor()

    try:
        # Get timeseries data
        timeseries_sql = f"""
            SELECT
                {date_trunc}::date as date,
                SUM(input_tokens) as input_tokens,
                SUM(output_tokens) as output_tokens,
                SUM(input_tokens + output_tokens) as total_tokens
            FROM token_usage
            WHERE user_id = %s AND raw_timestamp >= %s
            GROUP BY {date_trunc}::date
            ORDER BY date ASC
        """
        cur.execute(timeseries_sql, (user_id, since_ms))
        timeseries_rows = cur.fetchall()

        # Get summary data
        summary_sql = """
            SELECT
                SUM(input_tokens) as total_input_tokens,
                SUM(output_tokens) as total_output_tokens,
                SUM(input_tokens + output_tokens) as total_tokens,
                COUNT(*) as total_interactions
            FROM token_usage
            WHERE user_id = %s AND raw_timestamp >= %s
        """
        cur.execute(summary_sql, (user_id, since_ms))
        summary_row = cur.fetchone()

        # Format timeseries
        timeseries = []
        for row in timeseries_rows:
            timeseries.append({
                "date": row["date"].isoformat() if row["date"] else None,
                "input_tokens": int(row["input_tokens"] or 0),
                "output_tokens": int(row["output_tokens"] or 0),
                "total_tokens": int(row["total_tokens"] or 0)
            })

        # Format summary
        summary = {
            "total_input_tokens": int(summary_row["total_input_tokens"] or 0),
            "total_output_tokens": int(summary_row["total_output_tokens"] or 0),
            "total_tokens": int(summary_row["total_tokens"] or 0),
            "total_interactions": int(summary_row["total_interactions"] or 0)
        }

        return jsonify({
            "ok": True,
            "data": {
                "timeseries": timeseries,
                "summary": summary
            }
        })

    except Exception as e:
        logger.exception("Analytics query failed: %s", e)
        return jsonify({"ok": False, "error": "Analytics query failed", "details": str(e)}), 500
    finally:
        return_db_connection(conn)
