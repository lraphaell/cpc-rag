"""Here are define pytest fixtures, hooks and plugins."""

import pytest
from flask import Flask

from app import create_app


@pytest.fixture
def app() -> Flask:
    """App fixture."""
    flask_app = create_app()
    return flask_app
