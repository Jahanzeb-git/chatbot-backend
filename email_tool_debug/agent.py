"""
DEBUG Email Tool Agent
Print statements instead of logging, mock WebSocket.
"""

import asyncio
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from flask import current_app

from .llm_client import EmailToolLLMClient
from .gmail_client import GmailClient, user_has_gmail_connected
from .prompt import (
    get_system_prompt,
    build_user_prompt_iteration_1,
    build_user_prompt_iteration_2_plus
)
from .schemas import Iteration1Output, ActionSchema, IterationResult
from db import get_db_connection, return_db_connection


class EmailToolAgent:
    """Debug email tool agent with print statements."""

    def __init__(self, user_id: int, session_id: str, user_query: str):
        print(f"\n{'='*60}")
        print(f"[Agent.__init__] Creating agent")
        print(f"    user_id: {user_id}")
        print(f"    session_id: {session_id}")
        print(f"    user_query: {user_query}")
        print(f"{'='*60}\n")
        
        self.user_id = user_id
        self.session_id = session_id
        self.user_query = user_query

        # State
        self.iteration_history: List[IterationResult] = []
        self.conversation_history: Optional[List[Dict[str, str]]] = None

        # Clients
        self.llm_client = EmailToolLLMClient()
        self.gmail_client = None

    def _mock_websocket(self, event: str, data: Dict[str, Any]):
        """Mock WebSocket - just print."""
        print(f"\n📡 WEBSOCKET EVENT: {event}")
        print(f"   Data: {data}\n")

    async def execute(self) -> Dict[str, Any]:
        """Execute email tool agent."""
        print(f"\n{'🚀'*20}")
        print(f"[Agent.execute] STARTING EXECUTION")
        print(f"{'🚀'*20}\n")

        try:
            # Check Gmail connection
            print(f"[Agent.execute] Checking Gmail connection...")
            if not user_has_gmail_connected(self.user_id):
                print(f"[Agent.execute] ❌ Gmail not connected!")
                self._mock_websocket('email_tool_needs_auth', {
                    'message': 'Please connect your Gmail account'
                })
                return {'success': False, 'error': 'Gmail not connected', 'needs_auth': True}
            
            print(f"[Agent.execute] ✅ Gmail is connected")

            # Initialize Gmail client
            print(f"[Agent.execute] Initializing GmailClient...")
            self.gmail_client = GmailClient(self.user_id)
            self.user_email = self._get_user_email()
            print(f"[Agent.execute] ✅ User email: {self.user_email}")

            # Iteration 1: Check if conversation history is needed
            print(f"\n{'='*60}")
            print(f"[Agent.execute] ITERATION 1: Checking conversation history need")
            print(f"{'='*60}")
            needs_history = await self._iteration_1()
            print(f"[Agent.execute] Needs history: {needs_history}")

            # Fetch conversation history if needed
            if needs_history:
                print(f"[Agent.execute] Fetching conversation history...")
                self.conversation_history = self._fetch_conversation_history()

            # Iteration 2+: Agentic action loop
            print(f"\n{'='*60}")
            print(f"[Agent.execute] STARTING AGENTIC LOOP (Iteration 2+)")
            print(f"{'='*60}")
            result = await self._agentic_loop()

            # Send completion
            self._mock_websocket('email_tool_completed', {'result': result})

            print(f"\n{'✅'*20}")
            print(f"[Agent.execute] EXECUTION COMPLETE")
            print(f"{'✅'*20}\n")

            return result

        except Exception as e:
            print(f"\n{'❌'*20}")
            print(f"[Agent.execute] EXECUTION FAILED!")
            print(f"[Agent.execute] Exception type: {type(e).__name__}")
            print(f"[Agent.execute] Exception message: {str(e)}")
            print(f"[Agent.execute] Exception repr: {repr(e)}")
            print(f"[Agent.execute] Exception args: {e.args}")
            print(f"{'❌'*20}\n")
            
            import traceback
            print(f"[Agent.execute] Full traceback:")
            traceback.print_exc()
            
            self._mock_websocket('email_tool_error', {'error': str(e)})
            return {'success': False, 'error': str(e)}

    async def _iteration_1(self) -> bool:
        """Iteration 1: Decide if conversation history is needed."""
        print(f"\n[Agent._iteration_1] Building prompts...")
        
        system_prompt = get_system_prompt(iteration=1)
        user_prompt = build_user_prompt_iteration_1(self.user_query)
        
        print(f"[Agent._iteration_1] Calling LLM...")
        output = self.llm_client.generate_json(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            iteration=1,
            temperature=0.3,
            max_tokens=512
        )
        
        print(f"[Agent._iteration_1] LLM output: {output}")
        
        result = Iteration1Output(**output)
        
        self._mock_websocket('email_tool_progress', {
            'iteration': 1,
            'reasoning': result.reasoning
        })
        
        print(f"[Agent._iteration_1] ✅ needs_history={result.needs_conversation_history}")
        return result.needs_conversation_history

    def _fetch_conversation_history(self) -> List[Dict[str, str]]:
        """Fetch conversation history from database."""
        print(f"[Agent._fetch_conversation_history] Fetching from DB...")
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """SELECT prompt, response FROM chat_history
                   WHERE user_id = %s AND session_number = %s
                   ORDER BY timestamp ASC
                   LIMIT 10""",
                (self.user_id, int(self.session_id))
            )
            rows = cursor.fetchall()

            messages = []
            for row in rows:
                messages.append({'role': 'user', 'content': row['prompt']})
                messages.append({'role': 'assistant', 'content': row['response']})

            print(f"[Agent._fetch_conversation_history] ✅ Fetched {len(messages)} messages")
            return messages
        finally:
            return_db_connection(conn)

    def _get_user_email(self) -> str:
        """Get user's Gmail email address from database."""
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT email_address FROM user_gmail_tokens WHERE user_id = %s",
                (self.user_id,)
            )
            row = cursor.fetchone()
            if row and row['email_address']:
                return row['email_address']
            return "your email"
        finally:
            return_db_connection(conn)

    async def _agentic_loop(self) -> Dict[str, Any]:
        """Iteration 2+: Agentic action loop."""
        iteration = 2
        max_iterations = 10

        while iteration <= max_iterations:
            print(f"\n{'='*60}")
            print(f"[Agent._agentic_loop] ITERATION {iteration}")
            print(f"{'='*60}")

            # Build context
            context = {
                'current_date': datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                'user_timezone': 'UTC'
            }

            # Build prompts
            system_prompt = get_system_prompt(
                iteration=iteration,
                current_date=context['current_date'],
                user_email=self.user_email
            )
            user_prompt = build_user_prompt_iteration_2_plus(
                user_query=self.user_query,
                conversation_history=self.conversation_history,
                iteration_history=[vars(ih) for ih in self.iteration_history],
                current_iteration=iteration,
                context=context
            )

            print(f"[Agent._agentic_loop] User prompt preview:")
            print(f"{user_prompt[:500]}...")

            # Call LLM
            print(f"\n[Agent._agentic_loop] Calling LLM...")
            output = self.llm_client.generate_json(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                iteration=iteration,
                temperature=0.3,
                max_tokens=1024
            )

            print(f"[Agent._agentic_loop] LLM output: {output}")

            # Parse output
            action = ActionSchema(**output)
            print(f"[Agent._agentic_loop] Parsed action:")
            print(f"    function: {action.function}")
            print(f"    parameters: {action.parameters}")
            print(f"    reasoning: {action.reasoning}")

            # Send reasoning to frontend
            self._mock_websocket('email_tool_progress', {
                'iteration': iteration,
                'reasoning': action.reasoning
            })

            # Check if agent wants to exit
            if action.function is None:
                print(f"\n[Agent._agentic_loop] ✅ Agent completed! No more functions to call.")
                return self._build_comprehensive_result(
                    final_reasoning=action.reasoning,
                    total_iterations=iteration
                )

            # Execute function
            print(f"\n[Agent._agentic_loop] Executing function: {action.function}")
            function_result = await self._execute_gmail_function(
                action.function, 
                action.parameters or {}
            )
            print(f"[Agent._agentic_loop] Function result: {function_result}")

            # Store iteration result
            self.iteration_history.append(IterationResult(
                iteration_number=iteration,
                reasoning=action.reasoning,
                function=action.function,
                parameters=action.parameters,
                result=function_result
            ))

            iteration += 1

        print(f"\n[Agent._agentic_loop] ⚠️ Max iterations ({max_iterations}) reached!")
        return {
            'success': False,
            'error': 'Max iterations reached',
            'message': 'Email tool took too many steps.'
        }

    def _normalize_parameters(self, function_name: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize LLM-generated parameter names."""
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
                    print(f"[Agent._normalize_parameters] Normalized: '{shorthand}' -> '{actual}'")

        return normalized

    async def _execute_gmail_function(self, function_name: str, parameters: Dict[str, Any]) -> Any:
        """Execute Gmail function."""
        try:
            normalized_params = self._normalize_parameters(function_name, parameters)
            print(f"[Agent._execute_gmail_function] Executing: {function_name}({normalized_params})")

            function_map = {
                'search_emails': self.gmail_client.search_emails,
                'read_email': self.gmail_client.read_email,
                'send_email': self.gmail_client.send_email,
                'create_draft': self.gmail_client.create_draft,
                'mark_as_read': self.gmail_client.mark_as_read,
                'mark_as_unread': self.gmail_client.mark_as_unread,
                'list_labels': self.gmail_client.list_labels
            }

            if function_name not in function_map:
                raise ValueError(f"Unknown function: {function_name}")

            result = await function_map[function_name](**normalized_params)

            print(f"[Agent._execute_gmail_function] ✅ Success!")
            return {
                'success': True,
                'result': result
            }

        except Exception as e:
            print(f"[Agent._execute_gmail_function] ❌ FAILED!")
            print(f"[Agent._execute_gmail_function] Exception type: {type(e).__name__}")
            print(f"[Agent._execute_gmail_function] Exception message: {str(e)}")
            import traceback
            traceback.print_exc()
            return {
                'success': False,
                'error': str(e)
            }

    def _build_comprehensive_result(self, final_reasoning: str, total_iterations: int) -> Dict[str, Any]:
        """Build comprehensive result."""
        formatted_iterations = []
        for iter_result in self.iteration_history:
            iter_data = {
                'iteration': iter_result.iteration_number,
                'reasoning': iter_result.reasoning,
                'function': iter_result.function,
                'parameters': iter_result.parameters,
                'result': iter_result.result
            }
            formatted_iterations.append(iter_data)

        result = {
            'success': True,
            'summary': final_reasoning,
            'total_iterations': total_iterations,
            'iterations': formatted_iterations,
            'final_reasoning': final_reasoning
        }

        print(f"[Agent._build_comprehensive_result] Built result with {len(formatted_iterations)} iterations")
        return result


async def run_agent(user_id: int, session_id: str, query: str) -> Dict[str, Any]:
    """Run the debug agent."""
    agent = EmailToolAgent(
        user_id=user_id,
        session_id=session_id,
        user_query=query
    )
    return await agent.execute()
