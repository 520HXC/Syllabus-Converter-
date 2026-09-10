from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import router
from .config import get_settings
from .database import Base, configure_database
from .upload_body import UploadBodyLimitMiddleware


def create_app() -> FastAPI:
    settings = get_settings()
    engine, session_factory = configure_database(settings.database_url)
    if settings.database_url.startswith("sqlite"):
        Base.metadata.create_all(engine)

    application = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )
    application.state.session_factory = session_factory
    application.state.settings = settings
    application.add_middleware(UploadBodyLimitMiddleware, settings=settings)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.include_router(router, prefix=settings.api_prefix)
    return application


app = create_app()
