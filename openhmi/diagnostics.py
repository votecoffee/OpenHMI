"""Read-only runtime diagnostics projection, independent of HTTP registration.

Capture driver samples, catalog, project and route status under its shared lock.
Filtering and rendering run after release; worker health has its own snapshot.
This service never acquires subscriptions or performs controller I/O.
"""

import time


def runtime_diagnostics(driver, workers, search='', quality='all', connection_filter='', offset=0, limit=100):
    with driver.lock:
        now = time.monotonic()
        samples = driver.sample_snapshot(now, include_values=False)
        sources, definitions = driver.sources, driver.definitions
        project, plc_hold = driver.project, driver.plc_hold
        live = {connection['id']: connection for connection in driver.status(include_timing=True, now=now)}
    query = search.casefold()
    names = (name for name, sample in samples.items() if query in name.casefold()
             and (quality == 'all' or sample['quality'] == quality
                  or (quality == 'non-good' and sample['quality'] != 'good')))
    wanted_connection = '' if connection_filter == ':local' else connection_filter
    matches = []
    for name in names:
        root, member = sources.get(name, (None, ''))
        definition = definitions.get(root)
        connection = definition['connection'] if definition else ''
        if not connection_filter or connection == wanted_connection:
            matches.append((name, definition, member, connection))
    matches.sort(key=lambda binding: binding[0])
    tags = []
    for name, definition, member, connection in matches[offset:offset + limit]:
        sample = samples[name]
        tags.append({'name': name, 'connection': connection,
                     'address': definition['address'] + ('.' + member if member else '') if definition and definition['connection'] else 'Local HMI',
                     'type': definition['members'][member] if definition and member else definition['type'] if definition else sample['value_type'],
                     'quality': sample['quality'], 'timestamp': sample.get('timestamp'), 'age_seconds': sample.get('age_seconds', 0 if sample['quality'] == 'good' else None),
                     'error': sample.get('error')})
    connections = []
    for config in (project or {}).get('connections', []):
        status = live.get(config['id'], {})
        state = (
            'disabled' if not config['enabled'] else
            'held' if plc_hold else
            'scan overdue' if status.get('scan_overdue') else
            'recovering' if status.get('recovering') else
            'waiting for first good data' if status.get('awaiting_data') else
            'no usable data' if status.get('data_unavailable') else
            'connected' if status.get('connected') else 'disconnected'
        )
        connections.append({'id': config['id'], 'name': config['name'], 'path': config['path'], 'state': state,
                            'connection_instance': status.get('connection_instance'),
                            'scan_age_seconds': status.get('scan_age_seconds'),
                            'error': status.get('error'), 'read_calls': status.get('read_calls', 0), 'tags_read': status.get('tags_read', 0), 'groups': status.get('groups', []),
                            'timings': status.get('timings', {}), 'route_failures': status.get('route_failures', 0)})
    return {'workers': workers.snapshot(), 'connections': connections, 'tags': tags, 'total_tags': len(matches), 'offset': offset,
            'next_offset': offset + limit if offset + limit < len(matches) else None, 'truncated': offset + limit < len(matches),
            'plc_hold': plc_hold, 'counter_scope': 'pycomm3 read calls and requested addresses; not wire-packet measurements', 'scan_timing': 'best effort'}
