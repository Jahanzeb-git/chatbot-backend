"""
Tool registry and execution handler for Deepthinks AI Assistant.
Supports async tool execution with error handling.
"""

import logging
from typing import Dict, Any, Optional
from .search_web import search_web_tool

# Tool registry mapping tool names to their execution functions
TOOL_REGISTRY = {
    "search_web": search_web_tool,
}

async def execute_tool(tool_name: str, tool_input: Dict[str, Any]) -> Dict[str, Any]:
    """
    Execute a tool by name with given input.

    Args:
        tool_name: Name of the tool to execute
        tool_input: Dictionary containing tool parameters

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