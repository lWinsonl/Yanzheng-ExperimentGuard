from app.api import agent, facts, materials, recheck, review, sessions

ALL_ROUTERS = [
    sessions.router,
    materials.router,
    facts.router,
    review.router,
    recheck.router,
    agent.router,
]

__all__ = ["ALL_ROUTERS"]