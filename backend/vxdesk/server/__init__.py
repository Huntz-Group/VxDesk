"""FastAPI app: REST + WebSocket surface defined in ``docs/api-contract.md``."""

from .app import create_app

__all__ = ["create_app"]
