"""
Test script to isolate the search_emails error.
Tests the parameter passing to understand the exact error.
"""

import asyncio
import sys

# Test 1: Direct function call simulation with different param names
def test_parameter_passing():
    """Test what happens when we pass different parameter names."""
    
    print("=" * 60)
    print("TEST 1: Parameter Name Behavior")
    print("=" * 60)
    
    # Simulating the gmail_client.search_emails function signature
    def mock_search_emails(
        from_addr=None,
        to_addr=None,
        subject=None,
        is_unread=None,
        date_after=None,
        date_before=None,
        query=None,
        max_results=10
    ):
        return f"Called with: from_addr={from_addr}, to_addr={to_addr}, subject={subject}"
    
    # Test Case A: Correct parameter name
    print("\n[A] Using 'from_addr' (correct):")
    try:
        params = {"from_addr": "test@example.com", "subject": "meeting"}
        result = mock_search_emails(**params)
        print(f"   ✅ SUCCESS: {result}")
    except Exception as e:
        print(f"   ❌ ERROR: {type(e).__name__}: {e}")
    
    # Test Case B: Wrong parameter name 'from'
    print("\n[B] Using 'from' (wrong - reserved keyword):")
    try:
        params = {"from": "test@example.com", "subject": "meeting"}
        result = mock_search_emails(**params)
        print(f"   ✅ SUCCESS: {result}")
    except Exception as e:
        print(f"   ❌ ERROR: {type(e).__name__}: {e}")
    
    # Test Case C: Wrong parameter name 'to'
    print("\n[C] Using 'to' (wrong):")
    try:
        params = {"to": "test@example.com", "subject": "meeting"}
        result = mock_search_emails(**params)
        print(f"   ✅ SUCCESS: {result}")
    except Exception as e:
        print(f"   ❌ ERROR: {type(e).__name__}: {e}")


def test_normalize_parameters():
    """Test the normalize_parameters logic."""
    
    print("\n" + "=" * 60)
    print("TEST 2: Parameter Normalization")
    print("=" * 60)
    
    def _normalize_parameters(function_name, parameters):
        if not parameters:
            return {}
        
        normalized = parameters.copy()
        
        param_mappings = {
            'search_emails': {
                'from': 'from_addr',
                'to': 'to_addr',
            }
        }
        
        if function_name in param_mappings:
            for shorthand, actual in param_mappings[function_name].items():
                if shorthand in normalized and actual not in normalized:
                    normalized[actual] = normalized.pop(shorthand)
                    print(f"   Normalized: '{shorthand}' -> '{actual}'")
        
        return normalized
    
    # Test normalization
    print("\n[A] Input: {'from': 'test@example.com'}")
    result = _normalize_parameters('search_emails', {'from': 'test@example.com'})
    print(f"   Output: {result}")
    
    print("\n[B] Input: {'from_addr': 'test@example.com'}")
    result = _normalize_parameters('search_emails', {'from_addr': 'test@example.com'})
    print(f"   Output: {result}")
    
    print("\n[C] Input: {'from': 'a', 'to': 'b', 'subject': 'c'}")
    result = _normalize_parameters('search_emails', {'from': 'a', 'to': 'b', 'subject': 'c'})
    print(f"   Output: {result}")


def test_actual_gmail_client():
    """Test actual GmailClient if credentials available."""
    
    print("\n" + "=" * 60)
    print("TEST 3: Actual GmailClient (requires Flask app context)")
    print("=" * 60)
    
    try:
        # Try to import and test
        from app import create_app
        app = create_app()
        
        with app.app_context():
            from tools.email_tool.gmail_client import GmailClient, user_has_gmail_connected
            
            # Check if user 43 has Gmail connected
            user_id = 43  # testuser5
            if user_has_gmail_connected(user_id):
                print(f"\n   User {user_id} has Gmail connected")
                
                try:
                    client = GmailClient(user_id)
                    print("   ✅ GmailClient initialized")
                    
                    # Try search with correct params
                    print("\n   Testing search_emails with from_addr='Affan'...")
                    result = asyncio.run(client.search_emails(from_addr="Affan", max_results=3))
                    print(f"   ✅ Result: {result}")
                    
                except Exception as e:
                    print(f"   ❌ GmailClient error: {type(e).__name__}: {e}")
            else:
                print(f"\n   User {user_id} has NOT connected Gmail")
                
    except ImportError as e:
        print(f"\n   ⚠️  Cannot import app (expected if running standalone): {e}")
    except Exception as e:
        print(f"\n   ❌ Error: {type(e).__name__}: {e}")


if __name__ == "__main__":
    print("\n🔍 Email Search Parameter Test\n")
    
    test_parameter_passing()
    test_normalize_parameters()
    
    # Only run actual client test if --live flag passed
    if "--live" in sys.argv:
        test_actual_gmail_client()
    else:
        print("\n" + "=" * 60)
        print("To test actual GmailClient, run: python test_email_search.py --live")
        print("=" * 60)
    
    print("\n✅ Tests complete!\n")
