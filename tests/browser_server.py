"""Explicit browser-test entry point with synthetic accounts; never used by the CLI."""
from openhmi.recipe_auth import hash_password
from openhmi.server import create_app


def create_test_app():
    encoded = hash_password('RecipeTestOnly-2026!')
    return create_app(recipe_users={'users': [
        {'name': 'engineer', 'roles': ['engineer', 'approver', 'operator'], 'password_hash': encoded},
        {'name': 'manager', 'roles': ['administrator'], 'password_hash': encoded},
    ]})
