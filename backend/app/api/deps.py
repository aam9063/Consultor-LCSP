"""FastAPI dependency providers (CL-04).

The LLM dependency exists so tests can override it with `FakeLLMClient`
instead of building the real NaN client.
"""

from typing import Annotated

from fastapi import Depends

from app.adapters.llm import LLMClient, NanLLMClient


def get_llm() -> LLMClient:
    """Provide the real LLM client; tests override this dependency."""
    return NanLLMClient()


LLMDep = Annotated[LLMClient, Depends(get_llm)]
