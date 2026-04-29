"""Shared Jinja2Templates instance for all mcontrol routes.

Slice 3 inlined `Jinja2Templates(directory=TEMPLATES_DIR)` in both
routes/home.py and routes/server.py. Slice 4 adds four more route
modules; sharing a single instance keeps configuration in one place.
"""

from pathlib import Path

from fastapi.templating import Jinja2Templates

TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=TEMPLATES_DIR)
