"""Entry point for running the webhook relay locally."""
from __future__ import annotations

from src.webhook_service import app, main

__all__ = ["app", "main"]


if __name__ == "__main__":
    main()
