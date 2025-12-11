"""
LLM Client for Email Tool Agent
Handles Together AI inference with structured JSON output support.
"""

import json
import logging
from together import Together
from flask import current_app
from typing import Dict, Any, List
from .schemas import get_schema_for_iteration


class EmailToolLLMClient:
    """
    LLM client for email tool agent using Together AI.
    Supports structured JSON outputs with Pydantic schema validation.
    """
    
    def __init__(self, api_key: str = None):
        """
        Initialize LLM client.
        
        Args:
            api_key: Together AI API key (if None, uses current_app.config)
        """
        if api_key is None:
            api_key = current_app.config.get('TOGETHER_API_KEY')
        
        if not api_key:
            raise ValueError("TOGETHER_API_KEY not provided and not found in app config")
        
        self.client = Together(api_key=api_key)
        self.model = current_app.config.get('DEFAULT_LLM', 'Qwen/Qwen3-235B-A22B-Instruct-2507-tput')
        
        logging.info(f"EmailToolLLMClient initialized with model: {self.model}")
    
    def generate_json(
        self,
        system_prompt: str,
        user_prompt: str,
        iteration: int,
        temperature: float = 0.3,
        max_tokens: int = 1024
    ) -> Dict[str, Any]:
        """
        Generate JSON response from LLM with structured output.
        
        Args:
            system_prompt: System prompt (iteration-specific)
            user_prompt: User prompt (with scratchpad)
            iteration: Iteration number (determines schema)
            temperature: Sampling temperature (lower = more deterministic)
            max_tokens: Maximum tokens to generate
        
        Returns:
            Parsed JSON dict from LLM
        
        Raises:
            Exception: If LLM call fails or JSON parsing fails
        """
        try:
            # Get appropriate schema for this iteration
            schema = get_schema_for_iteration(iteration)
            
            # Build messages
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ]
            
            logging.info(f"Calling Together AI for iteration {iteration}")
            logging.debug(f"System prompt length: {len(system_prompt)} chars")
            logging.debug(f"User prompt length: {len(user_prompt)} chars")
            
            # Call Together AI with structured output
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                response_format={
                    "type": "json_object",
                    "schema": schema
                }
            )
            
            # Extract and parse JSON
            content = response.choices[0].message.content
            
            if not content:
                raise ValueError("LLM returned empty response")
            
            # Parse JSON
            parsed = json.loads(content)
            
            logging.info(f"Successfully generated JSON for iteration {iteration}")
            logging.debug(f"Response: {json.dumps(parsed, indent=2)}")
            
            return parsed
        
        except json.JSONDecodeError as e:
            logging.error(f"Failed to parse LLM response as JSON: {e}")
            logging.error(f"Raw response: {content if 'content' in locals() else 'N/A'}")
            raise Exception(f"LLM returned invalid JSON: {str(e)}")
        
        except Exception as e:
            logging.error(f"LLM inference failed: {e}", exc_info=True)
            raise Exception(f"LLM inference error: {str(e)}")
    
    def generate_json_with_history(
        self,
        system_prompt: str,
        messages: List[Dict[str, str]],
        iteration: int,
        temperature: float = 0.3,
        max_tokens: int = 1024
    ) -> Dict[str, Any]:
        """
        Generate JSON response with full message history (alternative method).
        Useful if you want to build messages manually instead of using system+user.
        
        Args:
            system_prompt: System prompt
            messages: List of message dicts [{"role": "user", "content": "..."}, ...]
            iteration: Iteration number
            temperature: Sampling temperature
            max_tokens: Max tokens
        
        Returns:
            Parsed JSON dict
        """
        try:
            schema = get_schema_for_iteration(iteration)
            
            # Prepend system message
            full_messages = [{"role": "system", "content": system_prompt}] + messages
            
            logging.info(f"Calling Together AI with {len(full_messages)} messages")
            
            response = self.client.chat.completions.create(
                model=self.model,
                messages=full_messages,
                temperature=temperature,
                max_tokens=max_tokens,
                response_format={
                    "type": "json_object",
                    "schema": schema
                }
            )
            
            content = response.choices[0].message.content
            parsed = json.loads(content)
            
            logging.info(f"Successfully generated JSON")
            
            return parsed
        
        except Exception as e:
            logging.error(f"LLM inference with history failed: {e}", exc_info=True)
            raise Exception(f"LLM inference error: {str(e)}")
