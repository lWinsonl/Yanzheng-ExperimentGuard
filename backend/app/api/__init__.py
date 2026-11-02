from app.api import agent, claim_graph, facts, followup, materials, recheck, review, sessions, version_diff

ALL_ROUTERS = [
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