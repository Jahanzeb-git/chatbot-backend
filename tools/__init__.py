"""
Tool registry and execution handler for Deepthinks AI Assistant.
Supports async tool execution with error handling.
"""

import logging
from typing import Dict, Any, Optional
from .search_web import search_web_tool
from .email_tool.agent import execute_email_tool

# Tool registry mapping tool names to their execution functions
TOOL_REGISTRY = {
    "search_web": search_web_tool,
    "email_tool": execute_email_tool,
}

async def execute_tool(
    tool_name: str, 
    tool_input: Dict[str, Any],
    user_id: Optional[int] = None,
    session_id: Optional[str] = None,
    socketio_instance = None
) -> Dict[str, Any]:
    """
    Execute a tool by name with given input.

    Args:
        tool_name: Name of the tool to execute
        tool_input: Dictionary containing tool parameters
        user_id: Optional user ID (required for email_tool)
        session_id: Optional session ID (required for email_tool)
        socketio_instance: Optional SocketIO instance (required for email_tool)

    Returns:
        Dictionary containing tool result or error information

    Format:
        Success: {"success": True, "result": {...}, "tool_name": "search_web"}
        Error: {"success": False, "error": "error message", "tool_name": "search_web"}
    """
    if tool_name not in TOOL_REGISTRY:
        logging.error(f"Unknown tool requested: {tool_name}")
        return {
            "success": False,
            "error": f"Unknown tool: {tool_name}",
            "tool_name": tool_name
        }

    try:
        tool_function = TOOL_REGISTRY[tool_name]
        
        # Special handling for email_tool which requires additional parameters
        if tool_name == "email_tool":
            if not user_id or not session_id:
                return {
                    "success": False,
                    "error": "email_tool requires user_id and session_id",
                    "tool_name": tool_name
                }
            result = await tool_function(
                user_id=user_id,
                session_id=str(session_id),
                query=tool_input.get('query', ''),
                socketio_instance=socketio_instance
            )
        else:
            # Standard tool execution
            result = await tool_function(tool_input)

        return {
            "success": True,
            "result": result,
            "tool_name": tool_name
        }

    except Exception as e:
        logging.error(f"Tool execution failed for {tool_name}: {e}", exc_info=True)
        return {
            "success": False,
            "error": str(e),
            "tool_name": tool_name
        }

def format_tool_result_for_llm(tool_result: Dict[str, Any]) -> str:
    """
    Format tool result for LLM consumption (raw JSON string).

    Args:
        tool_result: Tool execution result dictionary

    Returns:
        Formatted string for LLM context
    """
    import json
    return json.dumps(tool_result, indent=2, ensure_ascii=False)