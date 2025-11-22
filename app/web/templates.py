"""Shared Jinja2 templates configuration for the web app."""
from fastapi.templating import Jinja2Templates

templates = Jinja2Templates(directory="app/templates")
