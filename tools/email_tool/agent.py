"""
Email Tool Agent - Main Orchestration
Handles agentic loop with WebSocket updates and write operation approval.
"""

import logging
import asyncio
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from flask import current_app
import gevent  # For gevent-compatible sleep

from .llm_client import EmailToolLLMClient
from .gmail_client import GmailClient, user_has_gmail_connected
from .prompt import (
    get_system_prompt,
    build_user_prompt_iteration_1,
    build_user_prompt_iteration_2_plus
)
from .schemas import Iteration1Output, ActionSchema, IterationResult     
from db import get_db_connection, return_db_connection


# Global registry to track active agents for approval handling
_active_agents: Dict[str, 'EmailToolAgent'] = {}


def get_active_agent(user_id, session_id) -> Optional['EmailToolAgent']:
    """Get active agent for user/session."""
    # Ensure consistent key format regardless of input types
    key = f"{int(user_id)}_{str(session_id)}"
    agent = _active_agents.get(key)
    logging.info(f"Looking up agent with key: {key}, found: {agent is not None}")  
    return agent


def _register_agent(user_id: int, session_id: str, agent: 'EmailToolAgent'):       
    """Register active agent."""
    key = f"{user_id}_{session_id}"
    _active_agents[key] = agent
    logging.info(f"Registered agent: {key}")


def _unregister_agent(user_id: int, session_id: str):
    """Unregister agent."""
    key = f"{user_id}_{session_id}"
    if key in _active_agents:
        del _active_agents[key]
        logging.info(f"Unregistered agent: {key}")


class EmailToolAgent:
    """
    Email tool agent with agentic loop.
    Handles iteration-based execution with WebSocket progress updates.
    """

    def __init__(self, user_id: int, session_id: str, user_query: str, socketio_instance=None):
        """
        Initialize email tool agent.

        Args:
            user_id: User ID
            session_id: Session ID for WebSocket room
            user_query: Original user query
            socketio_instance: Flask-SocketIO instance for real-time updates       
        """
        self.user_id = user_id
        self.session_id = session_id
        self.user_query = user_query
        self.socketio = socketio_instance
        self.room = f"email_tool_{user_id}_{session_id}"

        # State
        self.iteration_history: List[IterationResult] = []
        self.conversation_history: Optional[List[Dict[str, str]]] = None
        self.needs_approval = False
        self.approval_received = None
        self.auth_completed = None  # For Gmail auth waiting

        # Clients
        self.llm_client = EmailToolLLMClient()
        self.gmail_client = None  # Initialized after auth check

        logging.info(f"EmailToolAgent initialized for user {user_id}, session {session_id}")

    def _send_websocket(self, event: str, data: Dict[str, Any]):
        """Send WebSocket event to user's room."""
        if self.socketio:
            try:
                logging.info(f"WebSocket ATTEMPTING: {event} to room {self.room} with data: {data}")

                # First, yield to gevent to ensure connection state is up-to-date  
                gevent.sleep(0)

                # Emit to specific room
                self.socketio.emit(event, data, room=self.room)
                logging.info(f"WebSocket SENT to room: {event} to room {self.room}")

                # Give gevent a chance to actually send the messages
                gevent.sleep(0.1)

            except Exception as e:
                logging.error(f"WebSocket EMIT ERROR: {event} to room {self.room}: {e}", exc_info=True)
        else:
            logging.warning(f"WebSocket SKIPPED (no socketio): {event} for room {self.room}")

    async def execute(self) -> Dict[str, Any]:
        """
        Execute email tool agent with agentic loop.

        Returns:
            Structured result for main chat LLM
        """
        # Register this agent for approval handling
        _register_agent(self.user_id, self.session_id, self)

        try:
            logging.info(f"=== EMAIL TOOL EXECUTE START === user={self.user_id}, session={self.session_id}, socketio={self.socketio is not None}")

            # Check if user has Gmail connected
            if not user_has_gmail_connected(self.user_id):
                logging.info(f"User {self.user_id} has not connected Gmail - requesting auth")

                # Reset auth state
                self.auth_completed = None

                # Send auth request via WebSocket
                self._send_websocket('email_tool_needs_auth', {
                    'message': 'Please connect your Gmail account to continue'     
                })

                # Wait for auth (max 2 minutes)
                max_wait_time = 120  # 2 minutes
                wait_interval = 1.0  # check every second
                elapsed_time = 0

                while self.auth_completed is None and elapsed_time < max_wait_time:                    # Use gevent.sleep for compatibility with gevent workers       
                    gevent.sleep(wait_interval)
                    elapsed_time += wait_interval
                    logging.info(f"Waiting for Gmail auth... {elapsed_time}s / {max_wait_time}s")

                    # Check if auth completed during wait
                    if user_has_gmail_connected(self.user_id):
                        self.auth_completed = True
                        break

                # Check result
                if not self.auth_completed:
                    logging.warning(f"Gmail auth timeout after {max_wait_time}s")  
                    self._send_websocket('email_tool_error', {
                        'error': 'Gmail authentication timed out. Please try again.'
                    })
                    return {
                        'success': False,
                        'error': 'Gmail authentication timed out',
                        'needs_auth': True
                    }

                logging.info(f"Gmail auth completed for user {self.user_id}")      

            # Initialize Gmail client
            self.gmail_client = GmailClient(self.user_id)
            # Fetch user's Gmail email address
            self.user_email = self._get_user_email()

            # Iteration 1: Check if conversation history is needed
            needs_history = await self._iteration_1()

            # Fetch conversation history if needed
            if needs_history:
                self.conversation_history = self._fetch_conversation_history()     

            # Iteration 2+: Agentic action loop
            result = await self._agentic_loop()

            # Send completion event
            logging.info(f"Final Email Tool Result: {result}")
            self._send_websocket('email_tool_completed', {
                'result': result
            })

            return result

        except Exception as e:
            logging.error(f"Email tool agent failed: {e}", exc_info=True)
            self._send_websocket('email_tool_error', {
                'error': str(e)
            })
            return {
                'success': False,
                'error': str(e)
            }

        finally:
            # Always unregister agent when done
            _unregister_agent(self.user_id, self.session_id)

    async def _iteration_1(self) -> bool:
        """
        Iteration 1: Decide if conversation history is needed.

        Returns:
            True if conversation history is needed, False otherwise
        """
        logging.info("=== Iteration 1: Checking conversation history need ===")    

        # Build prompt
        system_prompt = get_system_prompt(iteration=1)
        user_prompt = build_user_prompt_iteration_1(self.user_query)

        # Call LLM
        output = self.llm_client.generate_json(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            iteration=1,
            temperature=0.3,
            max_tokens=512
        )

        # Parse output
        result = Iteration1Output(**output)

        # Send reasoning to frontend
        self._send_websocket('email_tool_progress', {
            'iteration': 1,
            'reasoning': result.reasoning
        })

        logging.info(f"Iteration 1 result: needs_history={result.needs_conversation_history}")

        return result.needs_conversation_history

    def _fetch_conversation_history(self) -> List[Dict[str, str]]:
        """
        Fetch conversation history from database.

        Returns:
            List of message dicts [{"role": "user", "content": "..."}, ...]        
        """
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

            logging.info(f"Fetched {len(messages)} conversation history messages") 
            return messages

        finally:
            return_db_connection(conn)


    def _get_user_email(self) -> str:
        """
        Get user's Gmail email address from database.

        Returns:
            User's email address or 'Unknown'
        """
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
            else:
                logging.warning(f"No email found for user {self.user_id}")
                return "your email"

        finally:
            return_db_connection(conn)


    async def _agentic_loop(self) -> Dict[str, Any]:
        """
        Iteration 2+: Agentic action loop.

        Returns:
            Final structured result
        """
        iteration = 2
        max_iterations = 10

        while iteration <= max_iterations:
            logging.info(f"=== Iteration {iteration} ===")

            # Build context
            context = {
                'current_date': datetime.now(timezone.utc).strftime("%Y-%m-%d"),   
                'user_timezone': 'UTC'  # TODO: Get from user settings
            }

            # Build prompt with scratchpad
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

            # Call LLM
            output = self.llm_client.generate_json(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                iteration=iteration,
                temperature=0.3,
                max_tokens=1024
            )

            # Parse output
            action = ActionSchema(**output)

            # Send reasoning to frontend
            self._send_websocket('email_tool_progress', {
                'iteration': iteration,
                'reasoning': action.reasoning
            })

            # Check if agent wants to exit
            if action.function is None:
                logging.info(f"Agent completed at iteration {iteration}")

                # Store final iteration (reasoning-only, no function)
                self.iteration_history.append(IterationResult(
                    iteration_number=iteration,
                    reasoning=action.reasoning,
                    function=None,
                    parameters=None,
                    result={'success': True}  # No actual result for reasoning-only iterations
                ))

                # Build comprehensive result for main chat LLM
                return self._build_comprehensive_result(
                    final_reasoning=action.reasoning,
                    total_iterations=iteration
                )

            # Check if function requires approval (only send_email)
            if action.function == 'send_email':
                approved = await self._request_approval(action)
                if not approved:
                    return {
                        'success': False,
                        'message': 'User rejected email sending',
                        'cancelled': True
                    }

            # Execute function
            function_result = await self._execute_gmail_function(action.function, action.parameters or {})

            # Store iteration result (with function execution)
            self.iteration_history.append(IterationResult(
                iteration_number=iteration,
                reasoning=action.reasoning,
                function=action.function,
                parameters=action.parameters,
                result=function_result
            ))

            iteration += 1

        # Max iterations reached
        logging.warning(f"Max iterations ({max_iterations}) reached")
        return {
            'success': False,
            'error': 'Max iterations reached',
            'message': 'Email tool took too many steps. Please try a simpler request.'
        }

    async def _request_approval(self, action: ActionSchema) -> bool:
        """
        Request user approval for write operations via WebSocket.
        Waits for frontend to send approval response.

        Returns:
            True if approved, False if rejected
        """
        logging.info(f"Requesting approval for: {action.function}")

        # Reset approval state
        self.approval_received = None

        # Send approval request via WebSocket
        self._send_websocket('email_tool_request_approval', {
            'operation': action.function,
            'parameters': action.parameters,
            'reasoning': action.reasoning
        })

        # Wait for approval response (max 60 seconds)
        max_wait_time = 60
        wait_interval = 0.5
        elapsed_time = 0

        while self.approval_received is None and elapsed_time < max_wait_time:     
            # Use gevent.sleep for compatibility with gevent workers
            gevent.sleep(wait_interval)
            elapsed_time += wait_interval

        # Check result
        if self.approval_received is None:
            logging.warning(f"Approval timeout after {max_wait_time}s - rejecting")
            return False

        approved = self.approval_received
        logging.info(f"Approval received: {approved}")

        return approved

    def set_approval(self, approved: bool):
        """
        Called by WebSocket handler when user approves/rejects.

        Args:
            approved: True if user approved, False if rejected
        """
        self.approval_received = approved
        logging.info(f"Approval set to: {approved}")

    def set_auth_completed(self, completed: bool):
        """
        Called by WebSocket handler when Gmail OAuth completes.

        Args:
            completed: True if auth succeeded, False if failed/cancelled
        """
        self.auth_completed = completed
        logging.info(f"Auth completed set to: {completed}")

    def _normalize_parameters(self, function_name: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalize LLM-generated parameter names to match actual function signatures.
        Handles cases where LLM uses shorthand names like 'from' instead of 'from_addr'.

        Args:
            function_name: Name of the Gmail function
            parameters: Raw parameters from LLM

        Returns:
            Normalized parameters dict
        """
        if not parameters:
            return {}

        normalized = parameters.copy()

        # Parameter name mappings: LLM shorthand -> actual parameter name
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
                    logging.info(f"Normalized parameter: '{shorthand}' -> '{actual}'")

        return normalized

    async def _execute_gmail_function(self, function_name: str, parameters: Dict[str, Any]) -> Any:
        """
        Execute Gmail function.

        Args:
            function_name: Name of Gmail function
            parameters: Function parameters

        Returns:
            Function result or error dict
        """
        try:
            # Normalize parameters to handle LLM output variations
            normalized_params = self._normalize_parameters(function_name, parameters)
            logging.info(f"Executing: {function_name}({normalized_params})")

            # Map function names to GmailClient methods
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

            # Execute function with normalized parameters
            result = await function_map[function_name](**normalized_params)

            return {
                'success': True,
                'result': result
            }

        except Exception as e:
            logging.error(f"Function {function_name} failed: {e}", exc_info=True)  
            return {
                'success': False,
                'error': str(e)
            }

    def _build_comprehensive_result(self, final_reasoning: str, total_iterations: int) -> Dict[str, Any]:
        """
        Build comprehensive structured result for main chat LLM.
        Includes full iteration history with all function calls and results.       

        Args:
            final_reasoning: Final reasoning from agent
            total_iterations: Total number of iterations

        Returns:
            Rich structured data for main chat LLM
        """
        # Format iteration history
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

        # Build comprehensive result
        result = {
            'success': True,
            'summary': final_reasoning,
            'total_iterations': total_iterations,
            'iterations': formatted_iterations,
            'final_reasoning': final_reasoning
        }

        logging.info(f"Built comprehensive result with {len(formatted_iterations)} iterations")
        return result


# Main entry point for email tool
async def execute_email_tool(
    user_id: int,
    session_id: str,
    query: str,
    socketio_instance=None
) -> Dict[str, Any]:
    """
    Execute email tool agent.

    Args:
        user_id: User ID
        session_id: Session ID
        query: User query
        socketio_instance: Flask-SocketIO instance

    Returns:
        Structured result for main chat LLM
    """
    agent = EmailToolAgent(
        user_id=user_id,
        session_id=session_id,
        user_query=query,
        socketio_instance=socketio_instance
    )

    return await agent.execute()