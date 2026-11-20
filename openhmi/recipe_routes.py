"""Recipe HTTP adapter. Identity and policy checks stay on the server."""

from fastapi import HTTPException
from pydantic import Field
from .project_models import StrictModel
from .recipe_auth import RecipeAuth
from .recipe_models import ChangeReason, RecipeCreate, RecipeSave, RecipeTransition, RecipeSelect, RecipeTransfer, PolicyChange, SimulationPermit
from .recipe_transfers import RecipeTransfers
from .recipe_image_routes import add_recipe_image_routes
from .recipe_library_routes import add_recipe_library_read_routes, add_recipe_library_mutation_routes
from .recipe_transfer_routes import add_recipe_transfer_routes
from .recipes import RecipeService, RecipeError
from .recipe_auth_routes import COOKIE, APP_COOKIE, add_recipe_auth_routes, require_recipe_user


# Keep request-model ownership here for legacy imports and qualified OpenAPI refs.
class Login(StrictModel):
    name: str = Field(min_length=1, max_length=60)
    password: str = Field(min_length=1, max_length=256)


class Empty(StrictModel):
    pass


def add_recipe_routes(app, store, application, users=None, security=None, commands=None, activity=None):
    auth = RecipeAuth(users)
    service = RecipeService(store, application)
    app.state.recipes = application.recipes = service
    app.state.recipe_auth = auth
    transfers = app.state.recipe_transfers = RecipeTransfers(store, application, service, commands)

    def user(request):
        return require_recipe_user(request, auth, security)

    def invoke(method, *args):
        try:
            return method(*args)
        except RecipeError as error:
            raise HTTPException(error.status, str(error)) from error

    add_recipe_auth_routes(app, auth, security, Login, Empty)

    add_recipe_library_read_routes(app, service)

    add_recipe_transfer_routes(app, transfers, store, auth, security, activity, user, invoke)

    add_recipe_library_mutation_routes(app, service, user, invoke)

    add_recipe_image_routes(app, service, user, invoke)
