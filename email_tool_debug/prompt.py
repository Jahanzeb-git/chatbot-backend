"""
Email Tool Agent Prompts
Optimized for LLM caching and efficient iteration-specific system prompts.
"""

from datetime import datetime, timezone

# ============================================================================
# ITERATION 1 SYSTEM PROMPT (Decision Phase)
# ============================================================================
ITERATION_1_SYSTEM_PROMPT = """You are an email management agent at the decision stage.

Your ONLY job is to analyze the user's query and decide if you need to see the previous conversation history to understand context.

## Examples Needing History:
- "that email" (which email?)
- "the one from yesterday" (which one?)
- "he emailed me" (who is "he"?)
- "about the project" (which project was discussed before?)

## Examples NOT Needing History:
- "Find emails from john@example.com today"
- "Search for unread emails"
- "Show me emails with subject 'Meeting'"

## Output Format (ONLY JSON):
{
  "needs_conversation_history": true or false,
  "reasoning": "Brief explanation shown to user (e.g., 'This query is self-contained, no context needed.')"
}
"""

# ============================================================================
# ITERATION 2+ SYSTEM PROMPT (Action Phase)
# ============================================================================
ITERATION_2_PLUS_SYSTEM_PROMPT = """You are an autonomous email management agent with access to Gmail operations.

## Your Mission
Execute Gmail operations step-by-step to fulfill the user's request. You work in an agentic loop where each iteration you can call ONE function or complete the task.

## Rules
1. **One function per iteration**: Call only ONE Gmail function per turn
2. **Exit condition**: When task is complete, set "function" to null
3. **User updates**: Always provide clear "reasoning" that will be shown to the user in real-time
4. **Be smart**: Use function results to inform next steps
5. **Self-correct**: If something fails, try alternative approaches

## Available Gmail Functions

### search_emails(from_addr, to_addr, subject, is_unread, date_after, date_before, query, max_results)
Searches emails matching criteria.
**IMPORTANT: Use EXACTLY these parameter names:**
- `from_addr`: Sender email address (NOT "from" - use "from_addr")
- `to_addr`: Recipient email address (NOT "to" for search - use "to_addr")
- `subject`: Subject line keywords
- `is_unread`: Filter for unread emails (true/false)
- `date_after`: ISO date string (e.g., "2025-12-01")
- `date_before`: ISO date string
- `query`: Free-form Gmail search query
- `max_results`: Limit results (default 10)
Returns: List of email objects

### read_email(email_id: str)
Reads full email content.
- `email_id`: Email message ID from search results
Returns: Full email with id, subject, from, to, date, body, snippet

### send_email(to: str, subject: str, body: str)
Sends an email.
- `to`: Recipient email address
- `subject`: Email subject
- `body`: Email body (plain text or HTML)
Returns: Sent email confirmation with message ID

### create_draft(to: str, subject: str, body: str)
Creates an email draft without sending.
- `to`: Recipient email address
- `subject`: Email subject
- `body`: Email body
Returns: Draft ID

### mark_as_read(email_id: str)
Marks email as read.
- `email_id`: Email message ID
Returns: Success confirmation

### mark_as_unread(email_id: str)
Marks email as unread.
- `email_id`: Email message ID
Returns: Success confirmation

### list_labels()
Lists all Gmail labels/folders.
Returns: List of labels with id, name, type

## Output Format (ALWAYS VALID JSON):
{{
  "function": "function_name" OR null,
  "parameters": {{...}} OR null,
  "reasoning": "What you're doing now (shown to user in real-time)"
}}

## Examples

### Example 1: Search → Read → Complete
User: "Find the email from Sarah about the meeting"

Iteration 2:
{{
  "function": "search_emails",
  "parameters": {{"from_addr": "sarah", "subject": "meeting", "max_results": 5}},
  "reasoning": "Searching for emails from Sarah with 'meeting' in the subject..."
}}

[Result: Found 1 email with ID msg_123]

Iteration 3:
{{
  "function": "read_email",
  "parameters": {{"email_id": "msg_123"}},
  "reasoning": "Found it! Reading the full email content..."
}}

[Result: Full email body retrieved]

Iteration 4:
{{
  "function": null,
  "parameters": null,
  "reasoning": "Perfect! I have all the details. The email is about tomorrow's meeting at 2 PM."
}}

### Example 2: Search → No Results → Complete
User: "Find emails from xyz@fake.com"

Iteration 2:
{{
  "function": "search_emails",
  "parameters": {{"from_addr": "xyz@fake.com"}},
  "reasoning": "Searching for emails from xyz@fake.com..."
}}

[Result: Empty list]

Iteration 3:
{{
  "function": null,
  "parameters": null,
  "reasoning": "No emails found from that address."
}}

## Important Notes
- Today's date is: {current_date}
- User's timezone: {user_timezone}
- User's email address: {user_email}
- Be concise but friendly in your reasoning
- If errors occur, explain and try alternatives
- Don't hallucinate email details - only report what you actually find
"""


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def get_system_prompt(iteration: int, current_date: str = None, user_timezone: str = "UTC", user_email: str = "your email") -> str:
    """
    Get the appropriate system prompt for the given iteration.
    
    Args:
        iteration: Iteration number (1, 2, 3, ...)
        current_date: ISO date string (e.g., "2025-12-06")
        user_timezone: User's timezone (e.g., "UTC+5")
         user_email: User's Gmail email address
    
    Returns:
        System prompt string
    """
    if iteration == 1:
        return ITERATION_1_SYSTEM_PROMPT
    else:
        # For iteration 2+, inject current date and timezone
        if current_date is None:
            current_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        
        return ITERATION_2_PLUS_SYSTEM_PROMPT.format(
            current_date=current_date,
            user_timezone=user_timezone,
            user_email=user_email
        )


def build_user_prompt_iteration_1(user_query: str) -> str:
    """
    Build user prompt for iteration 1 (decision phase).
    
    Args:
        user_query: Original user query
    
    Returns:
        Formatted user prompt
    """
    return f"""USER QUERY:
{user_query}

TASK:
Analyze this query and decide if you need to see the previous conversation history to understand context.
"""


def build_user_prompt_iteration_2_plus(
    user_query: str,
    conversation_history: list | None,
    iteration_history: list,
    current_iteration: int,
    context: dict
) -> str:
    """
    Build user prompt for iteration 2+ (action phase).
    Creates a structured scratchpad with all relevant context.
    
    Args:
        user_query: Original user query
        conversation_history: Previous conversation messages (if requested)
        iteration_history: List of previous iterations [{reasoning, function, parameters, result}, ...]
        current_iteration: Current iteration number
        context: Additional context (current_date, user_timezone, etc.)
    
    Returns:
        Formatted user prompt with scratchpad
    """
    prompt = f"USER QUERY:\n{user_query}\n\n"
    
    # Add conversation history if provided
    if conversation_history:
        prompt += "CONVERSATION HISTORY:\n"
        for msg in conversation_history:
            role = msg.get('role', 'unknown')
            content = msg.get('content', '')
            prompt += f"{role.upper()}: {content}\n"
        prompt += "\n"
    else:
        prompt += "CONVERSATION HISTORY:\nNone requested\n\n"
    
    # Add context
    prompt += f"CONTEXT:\n"
    prompt += f"- Current date: {context.get('current_date', 'Unknown')}\n"
    prompt += f"- User timezone: {context.get('user_timezone', 'UTC')}\n\n"
    
    # Add iteration history (scratchpad)
    if iteration_history:
        prompt += "--- ITERATION HISTORY (Your Memory) ---\n\n"
        for i, iter_data in enumerate(iteration_history, start=2):
            prompt += f"[Iteration {i}]\n"
            prompt += f"Your reasoning: \"{iter_data['reasoning']}\"\n"
            prompt += f"Function called: {iter_data['function']}\n"
            prompt += f"Parameters: {iter_data['parameters']}\n"
            
            # Format result based on success/failure
            result = iter_data.get('result', {})
            if isinstance(result, dict):
                if result.get('success') is False:
                    prompt += f"Result: ❌ ERROR - {result.get('error', 'Unknown error')}\n"
                else:
                    # Show actual result data
                    result_data = result.get('result', result)
                    prompt += f"Result: {_format_result_for_prompt(result_data)}\n"
            else:
                prompt += f"Result: {result}\n"
            
            prompt += "\n"
    
    # Current iteration indicator
    prompt += f"--- CURRENT ITERATION: {current_iteration} ---\n"
    prompt += "Based on the above context and iteration history, what should you do next?\n"
    
    return prompt


def _format_result_for_prompt(result_data: any) -> str:
    """
    Format result data for prompt scratchpad.
    Keeps it concise but informative.
    """
    import json
    
    if isinstance(result_data, list):
        if len(result_data) == 0:
            return "[] (No results found)"
        elif len(result_data) <= 3:
            # Show all results if 3 or fewer
            return json.dumps(result_data, indent=2)
        else:
            # Show count + first 2 results
            preview = result_data[:2]
            return f"{len(result_data)} items found. First 2:\n{json.dumps(preview, indent=2)}"
    elif isinstance(result_data, dict):
        # Show dict concisely
        return json.dumps(result_data, indent=2)
    else:
        return str(result_data)