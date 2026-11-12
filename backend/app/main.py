from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.adapters.llm import LLMError, MissingAPIKeyError
from app.api.answers import router as answers_router
from app.api.health import router as health_router
from app.api.retrieval import router as retrieval_router

_MISSING_KEY_MESSAGE = "NAN_API_KEY is not configured; the LLM-backed endpoints are unavailable."


def _error_body(code: str, message: str) -> dict[str, Any]:
    return {"error": {"code": code, "message": message}}


async def _missing_api_key(_: Request, __: Exception) -> JSONResponse:
    # A missing key is a foreseeable configuration failure, never a bare 500.
    return JSONResponse(
        status_code=503, content=_error_body("llm_not_configured", _MISSING_KEY_MESSAGE)
    )


async def _llm_error(_: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=502, content=_error_body("llm_unavailable", str(exc)))


def create_app() -> FastAPI:
    app = FastAPI(title="Consultor LCSP", version="0.1.0")
    app.add_exception_handler(MissingAPIKeyError, _missing_api_key)
    app.add_exception_handler(LLMError, _llm_error)
    app.include_router(health_router)
    app.include_router(retrieval_router)
    app.include_router(answers_router)
    return app


app = create_app()
