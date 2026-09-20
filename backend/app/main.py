from fastapi import FastAPI

from app.api import (
    auth, admin_roles, academic, group, admin, upload, break_glass, lecturer,
)
from app.core.config import settings

app = FastAPI(
    title=settings.APP_NAME,
    debug=settings.DEBUG,
    version="0.1.0",
)

app.include_router(auth.router)
app.include_router(admin_roles.router)
app.include_router(academic.router)
app.include_router(group.router)
app.include_router(admin.router)
app.include_router(upload.router)
app.include_router(break_glass.router)
app.include_router(lecturer.router)


@app.get("/health", tags=["Health"])
def health_check():
    return {
        "status": "healthy",
        "app": settings.APP_NAME,
        "environment": settings.ENVIRONMENT,
    }