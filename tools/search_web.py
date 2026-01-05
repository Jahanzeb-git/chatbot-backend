"""
Tavily Web Search Tool Implementation
Provides real-time web search capabilities using Tavily API.
"""

import logging
import asyncio
from typing import Dict, Any
from tavily import TavilyClient
from flask import current_app

async def search_web_tool(tool_input: Dict[str, Any]) -> Dict[str, Any]:
    """
    Execute web search using Tavily API.

    Args:
        tool_input: Dictionary with 'query' key

    Returns:
        Raw Tavily API response dictionary

    Raises:
        ValueError: If query parameter is missing
        Exception: For API errors
    """
    query = tool_input.get('query')

    if not query:
        raise ValueError("Missing required parameter: 'query'")

    if not isinstance(query, str) or not query.strip():
        raise ValueError("Query must be a non-empty string")

    api_key = current_app.config.get('TAVILY_API_KEY')
    if not api_key:
        raise ValueError("TAVILY_API_KEY not configured in application config")

    logging.info(f"Executing web search for query: {query[:100]}")

    try:
        # Tavily client is synchronous, so we run it in executor
        loop = asyncio.get_event_loop()
        tavily_client = TavilyClient(api_key=api_key)

        # Run blocking call in thread pool
        response = await loop.run_in_executor(
            None,
            tavily_client.search,
            query
        )

        logging.info(f"Web search completed successfully. Found {len(response.get('results', []))} results")

        return response

    except Exception as e:
        logging.error(f"Tavily API error: {e}", exc_info=True)
Error: The handle is invalid.