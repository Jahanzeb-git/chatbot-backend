"""
Direct Gmail Client Test Script
Run this inside Fly.io container to test Gmail API without LLM.

Usage: python test_gmail_direct.py
"""

import asyncio
import sys
import traceback

def test_gmail_client():
    """Test GmailClient directly without LLM."""
    
    print("=" * 60)
    print("DIRECT GMAIL CLIENT TEST")
    print("=" * 60)
    
    # Import Flask app to get app context
    from app import create_app
    app = create_app()
    
    with app.app_context():
        from tools.email_tool.gmail_client import GmailClient, user_has_gmail_connected
        from db import get_db_connection, return_db_connection
        
        # Step 1: Find user ID for affansiddiqui2021@gmail.com
        print("\n[1] Finding user ID...")
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT id, email FROM users WHERE email = %s", ('affansiddiqui2021@gmail.com',))
            user_row = cursor.fetchone()
            
            if not user_row:
                print("ERROR: User not found!")
                return
            
            user_id = user_row['id']
            print(f"    Found user: id={user_id}, email={user_row['email']}")
        finally:
            return_db_connection(conn)
        
        # Step 2: Check if Gmail is connected
        print("\n[2] Checking Gmail connection...")
        if user_has_gmail_connected(user_id):
            print(f"    ✅ Gmail is connected for user {user_id}")
        else:
            print(f"    ❌ Gmail is NOT connected for user {user_id}")
            return
        
        # Step 3: Initialize GmailClient
        print("\n[3] Initializing GmailClient...")
        try:
            client = GmailClient(user_id)
            print("    ✅ GmailClient initialized successfully")
        except Exception as e:
            print(f"    ❌ GmailClient init failed: {type(e).__name__}: {e}")
            traceback.print_exc()
            return
        
        # Step 4: Test search_emails
        print("\n[4] Testing search_emails()...")
        try:
            # Simple search with no filters - should return recent emails
            result = asyncio.run(client.search_emails(max_results=3))
            print(f"    ✅ search_emails succeeded!")
            print(f"    Returned {len(result)} emails")
            for i, email in enumerate(result):
                print(f"\n    Email {i+1}:")
                print(f"      ID: {email.get('id', 'N/A')}")
                print(f"      Subject: {email.get('subject', 'N/A')[:50]}...")
                print(f"      From: {email.get('from', 'N/A')[:50]}...")
        except Exception as e:
            print(f"    ❌ search_emails failed!")
            print(f"    Exception type: {type(e).__name__}")
            print(f"    Exception args: {e.args}")
            print(f"    Exception str: {str(e)}")
            print("\n    Full traceback:")
            traceback.print_exc()
            return
        
        # Step 5: Test read_email (if we got results)
        print("\n[5] Testing read_email()...")
        if result and len(result) > 0:
            email_id = result[0]['id']
            try:
                email_content = asyncio.run(client.read_email(email_id))
                print(f"    ✅ read_email succeeded!")
                print(f"    Keys in result: {list(email_content.keys())}")
                print(f"    Subject: {email_content.get('subject', 'N/A')[:50]}...")
                body_preview = email_content.get('body', 'N/A')[:100].replace('\n', ' ')
                print(f"    Body preview: {body_preview}...")
            except Exception as e:
                print(f"    ❌ read_email failed!")
                print(f"    Exception type: {type(e).__name__}")
                print(f"    Exception args: {e.args}")
                print(f"    Exception str: {str(e)}")
                print("\n    Full traceback:")
                traceback.print_exc()
        else:
            print("    ⚠️ Skipped - no emails to read")
        
        print("\n" + "=" * 60)
        print("TEST COMPLETE")
        print("=" * 60)


if __name__ == "__main__":
    test_gmail_client()
