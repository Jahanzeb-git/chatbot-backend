"""
Email Tool Agent Diagnostic Script
Run inside Fly.io container to test the full agent flow with LLM.

This script:
1. Mocks WebSocket with print statements
2. Runs the full EmailToolAgent agentic loop
3. Shows all LLM calls, function executions, and results

Usage: /opt/venv/bin/python test_agent_flow.py
"""

import asyncio
import sys
import traceback


class MockSocketIO:
    """Mock SocketIO that prints events instead of sending."""
    
    def emit(self, event: str, data: dict, room: str = None):
        print(f"\n{'='*60}")
        print(f"📡 WEBSOCKET EVENT: {event}")
        print(f"   Room: {room}")
        print(f"   Data: {data}")
        print(f"{'='*60}\n")


def run_agent_test():
    """Test the full EmailToolAgent flow."""
    
    print("\n" + "🔬"*30)
    print("EMAIL TOOL AGENT DIAGNOSTIC TEST")
    print("🔬"*30 + "\n")
    
    # Import Flask app to get app context
    from app import create_app
    app = create_app()
    
    with app.app_context():
        from db import get_db_connection, return_db_connection
        from tools.email_tool.agent import EmailToolAgent
        from tools.email_tool.gmail_client import user_has_gmail_connected
        
        # Step 1: Find user ID
        print("[STEP 1] Finding user ID for affansiddiqui2021@gmail.com...")
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT id, email FROM users WHERE email = %s", ('affansiddiqui2021@gmail.com',))
            user_row = cursor.fetchone()
            if not user_row:
                print("ERROR: User not found!")
                return
            user_id = user_row['id']
            print(f"    ✅ Found user: id={user_id}, email={user_row['email']}")
        finally:
            return_db_connection(conn)
        
        # Step 2: Check Gmail connection
        print("\n[STEP 2] Checking Gmail connection...")
        if user_has_gmail_connected(user_id):
            print(f"    ✅ Gmail is connected for user {user_id}")
        else:
            print(f"    ❌ Gmail is NOT connected for user {user_id}")
            return
        
        # Step 3: Create mock SocketIO
        print("\n[STEP 3] Creating mock SocketIO...")
        mock_socketio = MockSocketIO()
        print("    ✅ Mock SocketIO created (will print events instead of sending)")
        
        # Step 4: Create EmailToolAgent
        print("\n[STEP 4] Creating EmailToolAgent...")
        test_query = "Show me my recent emails"
        session_id = "test_session_123"
        
        agent = EmailToolAgent(
            user_id=user_id,
            session_id=session_id,
            user_query=test_query,
            socketio_instance=mock_socketio
        )
        print(f"    ✅ Agent created")
        print(f"    Query: '{test_query}'")
        print(f"    Room: {agent.room}")
        
        # Step 5: Run the agent
        print("\n" + "🚀"*30)
        print("[STEP 5] RUNNING AGENT EXECUTE()...")
        print("🚀"*30 + "\n")
        
        try:
            result = asyncio.run(agent.execute())
            
            print("\n" + "✅"*30)
            print("AGENT EXECUTION COMPLETE!")
            print("✅"*30)
            print(f"\nFinal Result:")
            print(f"  Success: {result.get('success')}")
            
            if result.get('error'):
                print(f"  Error: {result.get('error')}")
                print(f"  Error Type: {result.get('error_type', 'N/A')}")
            
            if result.get('iterations'):
                print(f"  Total Iterations: {len(result.get('iterations', []))}")
                for i, iter_data in enumerate(result.get('iterations', [])):
                    print(f"\n  Iteration {i+1}:")
                    print(f"    Function: {iter_data.get('function')}")
                    print(f"    Parameters: {iter_data.get('parameters')}")
                    print(f"    Reasoning: {iter_data.get('reasoning', '')[:100]}...")
                    res = iter_data.get('result', {})
                    if isinstance(res, dict):
                        print(f"    Result success: {res.get('success')}")
                        if res.get('error'):
                            print(f"    Result error: {res.get('error')}")
            
            if result.get('summary'):
                print(f"\n  Summary: {result.get('summary')[:200]}...")
                
        except Exception as e:
            print("\n" + "❌"*30)
            print("AGENT EXECUTION FAILED!")
            print("❌"*30)
            print(f"\nException Type: {type(e).__name__}")
            print(f"Exception Message: {str(e)}")
            print(f"Exception Repr: {repr(e)}")
            print(f"Exception Args: {e.args}")
            print("\nFull Traceback:")
            traceback.print_exc()
        
        print("\n" + "🔬"*30)
        print("DIAGNOSTIC TEST COMPLETE")
        print("🔬"*30 + "\n")


if __name__ == "__main__":
    run_agent_test()
