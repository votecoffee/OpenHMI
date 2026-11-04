"""Explicit browser-test entry point with synthetic accounts; never used by the CLI."""
from openhmi.recipe_auth import hash_password
from openhmi.server import create_app


def create_test_app():
    encoded = hash_password('RecipeTestOnly-2026!')
    app = create_app(recipe_users={'users': [
        {'name': 'engineer', 'roles': ['engineer', 'approver', 'operator'], 'password_hash': encoded},
        {'name': 'manager', 'roles': ['administrator'], 'password_hash': encoded},
    ]})
    from tests.test_logix_history import FakePLC
    app.state.driver.factory = FakePLC  # This fixture can never open a network PLC connection.
    return app


def create_secure_test_app():
    from tests.test_security import bootstrap
    from openhmi.workspace import ProjectWorkspace
    from pathlib import Path
    from tempfile import TemporaryDirectory
    global _workspace_directory
    _workspace_directory = TemporaryDirectory(prefix='openhmi-browser-')
    workspace = ProjectWorkspace(Path(_workspace_directory.name) / 'Initial.openhmi.sqlite3')
    bootstrap(workspace.current)
    return workspace
