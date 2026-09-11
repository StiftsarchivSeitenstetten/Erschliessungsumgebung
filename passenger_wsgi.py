"""Passenger WSGI entrypoint for DomainFactory/cPanel.

Phusion Passenger expects a WSGI callable named ``application``. The project
itself is FastAPI/ASGI, so a2wsgi bridges the existing ASGI app to WSGI.
"""

from __future__ import annotations

from a2wsgi import ASGIMiddleware

from backend.main import app


application = ASGIMiddleware(app)
