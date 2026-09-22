from fastapi import FastAPI

from app.api import (
    auth, admin_roles, academic, group, admin, upload, break_glass, lecturer,
    combination, unit_offering, unit_proposal, registration_verification,
    election,
    community, group_transfer, cascade,
    solo_learner,
    impeachment,
    activity_club,
    financial,
    webhooks,
    unit_representation,
)
from app.core.config import settings

app = FastAPI(
    title=settings.APP_NAME,
    debug=settings.DEBUG,
    version="0.1.0",
)

# Module 001
app.include_router(auth.router)
app.include_router(admin_roles.router)
app.include_router(admin.router)
app.include_router(break_glass.router)
app.include_router(lecturer.router)

# Module 002
app.include_router(academic.router)
app.include_router(combination.router)
app.include_router(unit_offering.router)
app.include_router(unit_proposal.router)
app.include_router(registration_verification.router)
app.include_router(upload.router)

# Module 003
app.include_router(group.router)
app.include_router(election.router)
app.include_router(community.router)
app.include_router(group_transfer.router)
app.include_router(cascade.router)
app.include_router(solo_learner.router)
app.include_router(impeachment.router)
app.include_router(activity_club.router)

# Module 004
app.include_router(unit_representation.router)

# Module 012
app.include_router(financial.router)
app.include_router(webhooks.router)


@app.get("/health", tags=["Health"])
def health_check():
    return {
        "status": "healthy",
        "app": settings.APP_NAME,
        "environment": settings.ENVIRONMENT,
    }