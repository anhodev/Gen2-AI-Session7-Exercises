"""FastAPI app: create_app + lifespan + app.state.

Chạy:  myenv/bin/uvicorn app.main:app --reload --reload-dir app --port 8000
Swagger UI: http://localhost:8000/docs
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.agent import AgentSpec
from app.core.config import Settings, get_settings
from app.core.database import create_tables, make_session_factory
from app.core.router import router as core_router
from app.modules.invoices.agent import SPEC as INVOICES
from app.modules.invoices.router import router as invoices_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Khởi động: tạo bảng còn thiếu
    create_tables(app.state.engine)

    # Nạp dữ liệu mẫu của từng bài nếu database còn trống
    with app.state.session_factory() as db:
        for spec in app.state.agents.values():
            if spec.seed:
                spec.seed(db)

    yield  # app chạy trong lúc này

    # Tắt app: đóng kết nối database
    app.state.engine.dispose()


# Các bài đã làm. Mỗi bài khai báo một AgentSpec trong modules/<bài>/agent.py
AGENTS: list[AgentSpec] = [INVOICES]


def create_app(settings: Settings | None = None, agents: list[AgentSpec] | None = None) -> FastAPI:
    """
    Tạo FastAPI app.

    Args:
        settings (Settings | None, optional): Cấu hình. Test truyền vào để dùng
            SQLite tạm và chế độ mock. Defaults to get_settings().
        agents (list[AgentSpec] | None, optional): Các bài được chat. Test truyền bài giả.
            Defaults to AGENTS.

    Returns:
        FastAPI: App đã gắn database, CORS và các router.
    """
    settings = settings or get_settings()
    app = FastAPI(title="LangChain Tool Calling × Thuật toán", lifespan=lifespan)

    # Lưu engine, session factory và cấu hình vào app.state để endpoint dùng chung
    engine, session_factory = make_session_factory(settings.database_url)
    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.settings = settings
    app.state.agents = {spec.module: spec for spec in (AGENTS if agents is None else agents)}

    # Cho phép frontend (Next.js) gọi API từ trình duyệt
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_origin],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(core_router)
    app.include_router(invoices_router)
    return app


app = create_app()
