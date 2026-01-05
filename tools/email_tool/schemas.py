"""
Pydantic Schemas for Email Tool Agent
Provides type safety and JSON schema for LLM structured outputs.
"""

from pydantic import BaseModel, Field
from typing import Optional, Dict, Any


# ============================================================================
# ITERATION 1 OUTPUT SCHEMA
# ============================================================================

class Iteration1Output(BaseModel):
    """
    Schema for Iteration 1 output (decision phase).
    LLM decides if conversation history is needed.
    """
    needs_conversation_history: bool = Field(
        description="Whether the agent needs to see previous conversation messages"
    )
    reasoning: str = Field(
        description="Brief explanation shown to user in real-time"
    )


# ============================================================================
# ITERATION 2+ OUTPUT SCHEMA  
# ============================================================================

class ActionSchema(BaseModel):
    """
    Schema for Iteration 2+ output (action phase).
    LLM calls a Gmail function or exits loop.
    """
    function: Optional[str] = Field(
        default=None,
        description="Gmail function name to call, or null to exit loop"
    )
    parameters: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Parameters for the function, or null if function is null"
    )
    reasoning: str = Field(
        description="What the agent is doing now (shown to user via WebSocket)"
    )


# ============================================================================
# ITERATION TRACKING SCHEMA
# ============================================================================

class IterationResult(BaseModel):
    """
    Tracks a single iteration's input/output for scratchpad memory.
    Used to build the scratchpad context for subsequent iterations.
    """
    iteration_number: int = Field(description="Iteration number (1, 2, 3, ...)")
    reasoning: str = Field(description="LLM's reasoning for this iteration")
    function: Optional[str] = Field(default=None, description="Function called (if any)")
    parameters: Optional[Dict[str, Any]] = Field(default=None, description="Function parameters")
    result: Any = Field(default=None, description="Function execution result")


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def get_schema_for_iteration(iteration: int) -> Dict[str, Any]:
    """
    Get JSON schema for Together AI structured output based on iteration.
    
    Args:
        iteration: Iteration number (1, 2, 3, ...)
    
    Returns:
        JSON schema dict compatible with Together AI response_format
    """
    if iteration == 1:
        return Iteration1Output.model_json_schema()
    else:
        return ActionSchema.model_json_schema()


def validate_iteration_output(iteration: int, output: Dict[str, Any]) -> bool:
    """
    Validate LLM output against appropriate schema.
    
    Args:
        iteration: Iteration number
        output: LLM output dict
    
    Returns:
        True if valid, raises ValidationError if invalid
    """
    if iteration == 1:
        Iteration1Output(**output)  # Will raise if invalid
    else:
        ActionSchema(**output)  # Will raise if invalid
    return True