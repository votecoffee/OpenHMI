"""Ordered binding validation shared by draft, merge, staging and live apply."""

from .projects import Project
from .binding_project import (validate_protocols, build_tag_index, validate_identity,
                              validate_resources, validate_faceplates_and_history, expand_checked_controls)
from .binding_controls import validate_common_control, validate_edit_control, validate_action_or_value
from .binding_displays import validate_display_control
from .binding_charts import validate_chart_control


def create_binding_validator(application, security, canvas_images, web):
    def validate_bindings(project: Project):
        canvas_images.validate(project)
        validate_protocols(project, security)
        kinds, sources, routes = build_tag_index(project)
        validate_identity(project, security)
        actions = {action['name'] for action in application.actions()}
        validate_resources(project, kinds, web)
        project_data = project.model_dump()
        validate_faceplates_and_history(project, project_data, kinds)
        controls = expand_checked_controls(project_data)
        known_groups = {group['name'] for group in security.snapshot()['groups']}
        for control in controls:
            validate_common_control(control, project, kinds, known_groups)
            if control['kind'] in ('recipe', 'current_user', 'label', 'symbol', 'image'):
                continue
            if validate_edit_control(control, kinds, sources):
                continue
            if validate_display_control(control, kinds, sources, routes):
                continue
            if validate_chart_control(control, kinds):
                continue
            validate_action_or_value(control, project, kinds, actions, project_data)

    return validate_bindings
