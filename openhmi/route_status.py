"""Route diagnostic projection under the caller's runtime state lock.

Reads current state and returns independent DTOs. It never opens a connection,
acquires a route lock, schedules a scan or changes recovery state.
"""


def route_status(connections, scans, scan_started, rates, demanded_aliases,
                 has_usable_data, now, *, include_timing=False, include_groups=True):
    routes = []
    for identifier, connection in connections.items():
        scan = scans.get(identifier)
        age = max(0, now - scan_started[identifier]) if scan and not scan.done() else None
        groups = {}
        if include_groups:
            for (route, address), rate in rates.items():
                if route == identifier:
                    groups.setdefault(rate, []).append(address)
        active = connection.connected and bool(demanded_aliases.get(identifier))
        recovering = active and connection.outage_started is not None
        routes.append({'id': identifier, 'connected': connection.connected, 'error': connection.error,
                       'connection_instance': connection.instance,
                       'scan_age_seconds': age,
                       'recovering': recovering,
                       'awaiting_data': active and not recovering and not connection.has_usable_sample,
                       'data_unavailable': (active and not recovering and connection.has_usable_sample
                                            and not has_usable_data(identifier, connection.failure_generation, now)),
                       'scan_overdue': age is not None and age >= max(5, connection.config['timeout_seconds']),
                       'read_calls': connection.read_calls, 'tags_read': connection.tags_read,
                       **({'groups': [{'rate_ms': rate, 'addresses': sorted(addresses)}
                                      for rate, addresses in sorted(groups.items())]} if include_groups else {}),
                       **({'timings': connection.timings.snapshot(), 'route_failures': connection.failure_generation} if include_timing else {})})
    return routes
