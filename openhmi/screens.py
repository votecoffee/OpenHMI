"""Resolve screen identities and UDT-relative faceplate instances."""

from copy import deepcopy


CHART_TAG_FIELDS = {'bar': ('tag',), 'radar': ('tag',), 'pie': ('tag',), 'xy': ('x_tag', 'y_tag')}


def screen_map(project):
    return {'overview': {'id': 'overview', 'title': project['title'], 'columns': project['columns'],
                         'update_ms': project.get('update_ms', 500), 'controls': project['controls'], 'popup': False},
            **{screen['id']: screen for screen in project.get('screens', [])}}


def expanded_controls(project, screen_id=None):
    templates = {template['id']: template for template in project.get('faceplates', [])}
    result = []
    for identifier, screen in screen_map(project).items():
        if screen_id is not None and identifier != screen_id:
            continue
        for control in screen['controls']:
            base = deepcopy(control)
            base['id'] = control['id'] if identifier == 'overview' else f'{identifier}__{control["id"]}'
            base['_screen'] = identifier
            if control['kind'] != 'faceplate':
                result.append(base)
                continue
            template = templates.get(control['template'])
            if not template:
                raise ValueError('Unknown faceplate definition')
            for member in template['controls']:
                item = deepcopy(member)
                item['id'] = f'{base["id"]}__{member["id"]}'
                item['_screen'] = identifier
                for field in ('tag', 'target', 'visible_tag', 'enabled_tag', 'color_tag', 'minimum_tag', 'maximum_tag', 'min_length_tag', 'max_length_tag', 'address_tag', 'refresh_tag', 'confirmed_tag'):
                    if item.get(field, '').startswith('$.'):
                        item[field] = control['root_tag'] + item[field][1:]
                if item.get('tags'):
                    def resolve(tag):
                        return control['root_tag'] + tag[1:] if tag.startswith('$.') else tag

                    item['tags'] = [resolve(tag) for tag in item['tags']]
                    item['series'] = {resolve(tag): settings for tag, settings in item.get('series', {}).items()}
                    for field in ('start_tag', 'stop_tag'):
                        if item.get('recording'):
                            item['recording'][field] = resolve(item['recording'][field])
                for field in CHART_TAG_FIELDS.get(item['kind'], ()):
                    for series in item['series']:
                        if series[field].startswith('$.'):
                            series[field] = control['root_tag'] + series[field][1:]
                for check in item.get('checks', []):
                    if check['tag'].startswith('$.'):
                        check['tag'] = control['root_tag'] + check['tag'][1:]
                # Instance visibility/enable conditions apply in addition to member conditions.
                item['_parent_visible'] = base.get('visible_tag', '')
                item['_parent_enabled'] = base.get('enabled_tag', '')
                result.append(item)
    return result


def chart_tags(control):
    fields = CHART_TAG_FIELDS.get(control['kind'], ())
    return [series[field] for field in fields for series in control['series']]


def referenced_tags(control):
    fields = ('tag', 'visible_tag', 'enabled_tag', 'color_tag', '_parent_visible', '_parent_enabled', 'minimum_tag', 'maximum_tag', 'min_length_tag', 'max_length_tag', 'address_tag', 'refresh_tag', 'confirmed_tag')
    result = {control[field] for field in fields if control.get(field)}
    result.update(control.get('tags', []))
    result.update(check['tag'] for check in control.get('checks', []))
    result.update(chart_tags(control))
    if control.get('mode') in ('set', 'toggle') and control.get('target'):
        result.add(control['target'])
    return result


def enabled(control, values):
    return all(not control.get(field) or values.get(control[field]) is True
               for field in ('visible_tag', 'enabled_tag', '_parent_visible', '_parent_enabled'))
