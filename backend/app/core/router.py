"""Endpoint dùng chung: kiểm tra app đang chạy."""

from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter(tags=["Chung"])


@router.get("/health")
def health(request: Request):
    """
    Kiểm tra app đang chạy và đang dùng model/database nào.

    Returns:
        dict: Trạng thái app.
    """
    settings = request.app.state.settings
    return {
        "status": "ok",
        "llm": "mock" if settings.use_mock else settings.openai_model,
        "database": request.app.state.engine.dialect.name,  # postgresql hoặc sqlite
    }
