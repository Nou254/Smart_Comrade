from fastapi import FastAPI

from app.api import (
    auth, admin_roles, academic, group, admin, upload, break_glass, lecturer,
    combination, unit_offering, unit_proposal, registration_verification,
    election,
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

# Module 002 completion
app.include_router(combination.router)
app.include_router(unit_offering.router)
app.include_router(unit_proposal.router)
app.include_router(registration_verification.router)

# Module 003 Phase 6
app.include_router(election.router)


@app.get("/health", tags=["Health"])
def health_check():
    return {
        "status": "healthy",
        "app": settings.APP_NAME,
        "environment": settings.ENVIRONMENT,
    }