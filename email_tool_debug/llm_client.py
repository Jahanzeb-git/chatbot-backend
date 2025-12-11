"""
DEBUG LLM Client for Email Tool
Print statements instead of logging.
"""

import json
from together import Together
from flask import current_app
from typing import Dict, Any, List
from .schemas import get_schema_for_iteration


class EmailToolLLMClient:
    """LLM client with print statements for debugging."""
    
    def __init__(self, api_key: str = None):
        print(f"[LLMClient] Initializing...")
        if api_key is None:
            api_key = current_app.config.get('TOGETHER_API_KEY')
        
        if not api_key:
            raise ValueError("TOGETHER_API_KEY not provided and not found in app config")
        
        self.client = Together(api_key=api_key)
        self.model = current_app.config.get('DEFAULT_LLM', 'Qwen/Qwen3-235B-A22B-Instruct-2507-tput')
        print(f"[LLMClient] ✅ Initialized with model: {self.model}")
    
    def generate_json(
        self,
        system_prompt: str,
        user_prompt: str,
        iteration: int,
        temperature: float = 0.3,
        max_tokens: int = 1024
    ) -> Dict[str, Any]:
        """Generate JSON response from LLM."""
        print(f"\n[LLMClient.generate_json] Calling LLM for iteration {iteration}")
        print(f"[LLMClient.generate_json] System prompt length: {len(system_prompt)} chars")
        print(f"[LLMClient.generate_json] User prompt length: {len(user_prompt)} chars")
        
        try:
            schema = get_schema_for_iteration(iteration)
            
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ]
            
            print(f"[LLMClient.generate_json] Sending request to Together AI...")
            
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
            
            content = response.choices[0].message.content
            print(f"[LLMClient.generate_json] Got response, length: {len(content) if content else 0} chars")
            
            if not content:
                raise ValueError("LLM returned empty response")
            
            parsed = json.loads(content)
            print(f"[LLMClient.generate_json] ✅ Parsed JSON successfully")
            print(f"[LLMClient.generate_json] Response keys: {list(parsed.keys())}")
            print(f"[LLMClient.generate_json] Full response: {json.dumps(parsed, indent=2)}")
            
            return parsed
        
        except json.JSONDecodeError as e:
            print(f"[LLMClient.generate_json] ❌ JSON PARSE ERROR: {e}")
            print(f"[LLMClient.generate_json] Raw content: {content if 'content' in locals() else 'N/A'}")
            raise Exception(f"LLM returned invalid JSON: {str(e)}")
        
        except Exception as e:
            print(f"[LLMClient.generate_json] ❌ EXCEPTION: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
            raise Exception(f"LLM inference error: {str(e)}")
