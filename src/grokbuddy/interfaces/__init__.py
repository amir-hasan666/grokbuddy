"""Local Phase 2 client interfaces.

These adapters expose the in-process application service without adding a
second workflow or trusting caller-supplied production identities.
"""

from .gateway import ClientGateway, TOOL_NAMES

__all__ = ["ClientGateway", "TOOL_NAMES"]
