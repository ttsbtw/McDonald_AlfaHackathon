from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from .api import router
from .config import get_settings
from .db import create_database
from .errors import APIError, register_errors


def create_app(settings=None):
    settings = settings or get_settings()
    engine, session_factory = create_database(settings)

    @asynccontextmanager
    async def lifespan(app):
        yield
        engine.dispose()

    app = FastAPI(
        title="Умный кредитный кабинет — API заявок", version="0.3.0",
        description="Вход клиентов и сотрудников, каталог, заявки, оценки и очередь рассмотрения.",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = session_factory
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins,
                       allow_methods=["GET", "POST", "PATCH"],
                       allow_headers=["Authorization", "Content-Type"])
    register_errors(app)
    app.include_router(router)

    @app.get("/health", tags=["Состояние"])
    def health():
        return {"status": "ok"}

    @app.get("/ready", tags=["Состояние"])
    def ready():
        try:
            with engine.connect() as connection:
                version = connection.scalar(text("SELECT version_num FROM alembic_version"))
                if version != "0003_application_events":
                    raise APIError(503, "MIGRATIONS_REQUIRED", "Требуется применить миграции.")
        except SQLAlchemyError:
            raise APIError(503, "DATABASE_NOT_READY", "База данных ещё не готова.") from None
        return {"status": "ready"}

    return app
