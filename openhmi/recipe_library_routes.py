"""Recipe library HTTP adapters; service policy and persistence stay separate."""

from fastapi import Request
from .recipe_models import RecipeCreate, RecipeSave, RecipeTransition, RecipeSelect, PolicyChange, SimulationPermit


def add_recipe_library_read_routes(app, service):
    """Register public library and independent loaded-copy snapshots."""
    @app.get('/api/recipes')
    def recipes():
        return service.snapshot()

    @app.get('/api/recipes/selected')
    def selected():
        return service.selected()


def add_recipe_library_mutation_routes(app, service, user, invoke):
    """Register protected mutations with the assembly authorizer/error translator."""
    @app.post('/api/recipes')
    def create(body: RecipeCreate, request: Request):
        return invoke(service.create, body, user(request))

    @app.post('/api/recipes/{recipe_id}/revisions')
    def save(recipe_id: int, body: RecipeSave, request: Request):
        return invoke(service.save, recipe_id, body, user(request))

    @app.post('/api/recipe-revisions/{revision_id}/transition')
    def transition(revision_id: int, body: RecipeTransition, request: Request):
        return invoke(service.transition, revision_id, body, user(request))

    @app.post('/api/recipes/select')
    def select(body: RecipeSelect, request: Request):
        return invoke(service.select, body, user(request))

    @app.put('/api/recipes/policy')
    def policy(body: PolicyChange, request: Request):
        return invoke(service.update_policy, body, user(request))

    @app.post('/api/recipes/simulator-permit')
    def permit(body: SimulationPermit, request: Request):
        return invoke(service.simulator_permit, body, user(request))
