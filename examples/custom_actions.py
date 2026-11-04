"""Start with: openhmi --handlers examples/custom_actions.py

Select 'Half fill simulated tank' in an action button's Action property.
"""


def half_fill(app):
    app.driver.write("TankLevel", [50.0])


def register(app):
    app.register_action("half_fill", "Half fill simulated tank", half_fill)
