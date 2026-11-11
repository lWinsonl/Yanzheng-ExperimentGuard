from app.api import agent, auth, claim_graph, facts, followup, materials, recheck, review, sessions, version_diff

ALL_ROUTERS = [
    auth.router,
    sessions.router,
    materials.router,
    facts.router,
    review.router,
    recheck.router,
    agent.router,
    claim_graph.router,
    followup.router,
    version_diff.router,
]

__all__ = ["ALL_ROUTERS"]
