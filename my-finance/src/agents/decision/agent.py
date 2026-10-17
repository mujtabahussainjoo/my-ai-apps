"""decision review node, shared with the supervisor graph."""

from src.agents.specialists import baseline
from src.core.enums import AgentRole


def assess(state):
    return baseline(AgentRole.DECISION, state)
