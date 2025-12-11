#!/usr/bin/env python
"""
Email Tool Debug Runner
Run this to test the full agentic email tool flow with print statements.

Usage inside Fly.io container:
  /opt/venv/bin/python run_email_debug.py "show me my recent emails"
  /opt/venv/bin/python run_email_debug.py "find emails from Affan Siddiqui"
"""

import sys
import asyncio


def main():
    # Default query if none provided
    query = sys.argv[1] if len(sys.argv) > 1 else "show me my recent emails"
    
    print("\n" + "🔬"*30)
    print("EMAIL TOOL DEBUG RUNNER")
    print("🔬"*30)
    print(f"\nQuery: {query}\n")
    
    # Import Flask app for app context
    from app import create_app
    app = create_app()
    
    with app.app_context():
        from db import get_db_connection, return_db_connection
        
        # Find user ID
        print("[Setup] Finding user ID for affansiddiqui2021@gmail.com...")
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM users WHERE email = %s", ('affansiddiqui2021@gmail.com',))
            row = cursor.fetchone()
            if not row:
                print("ERROR: User not found!")
                return
            user_id = row['id']
            print(f"[Setup] ✅ User ID: {user_id}")
        finally:
            return_db_connection(conn)
        
        # Import and run debug agent
        from email_tool_debug.agent import run_agent
        
        print("\n[Setup] Starting debug agent...\n")
        
        result = asyncio.run(run_agent(
            user_id=user_id,
            session_id="debug_123",
            query=query
        ))
        
        print("\n" + "="*60)
        print("FINAL RESULT")
        print("="*60)
        print(f"Success: {result.get('success')}")
        if result.get('error'):
            print(f"Error: {result.get('error')}")
        if result.get('summary'):
            print(f"Summary: {result.get('summary')[:300]}...")
        print("="*60 + "\n")


if __name__ == "__main__":
    main()
