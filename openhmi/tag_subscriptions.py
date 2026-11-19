"""Viewer leases and logical tag demand; caller owns the runtime state lock.

No transport calls, sample storage, worker ownership or additional locks live here.
"""

from .screens import screen_map, expanded_controls, referenced_tags

MAX_VIEWER_LEASES = 1000
MAX_SUBSCRIPTION_SEQUENCES = 2 * MAX_VIEWER_LEASES


def build_screen_demands(project):
    screens = screen_map(project)
    screen_tags = {identifier: {} for identifier in screens}
    for control in expanded_controls(project):
        screen_tags[control['_screen']].update(dict.fromkeys(referenced_tags(control)))
    return {identifier: (screen.get('update_ms', 500), tuple(screen_tags[identifier]))
                      for identifier, screen in screens.items()}


class TagSubscriptions:
    def __init__(self):
        self.screen_demands = {}
        self.trend_demands = {}
        self.leases = {}
        self.sequences = {}

    def lease(self, client, screens, definitions, now, preview_root, *, sequence=None):
        if sequence is not None and sequence <= self.sequences.get(client, 0):
            return
        if any(screen not in self.screen_demands for screen in screens):
            raise ValueError('Unknown subscription screen')
        if preview_root and (preview_root not in definitions or definitions[preview_root]['type'] != 'struct'):
            raise ValueError('Faceplate preview requires a configured UDT tag')
        self.leases.pop(client, None)
        self.leases = {key: value for key, value in self.leases.items() if value[1] > now}
        if screens or preview_root:
            self.leases[client] = (screens, now + 15, preview_root)
        if len(self.leases) > MAX_VIEWER_LEASES:
            self.leases.pop(next(iter(self.leases)))
        if sequence is not None:
            # Retain the latest sequence even after a viewer releases its lease.
            self.sequences.pop(client, None)
            self.sequences[client] = sequence
            if len(self.sequences) > MAX_SUBSCRIPTION_SEQUENCES:
                self.sequences.pop(next(iter(self.sequences)))

    def demands(self, now, project):
        rates = {}
        def demand(tag, rate):
            rates[tag] = min(rate, rates.get(tag, rate))
        if not project:
            return rates
        wanted = set()
        for screens, expires_at, preview_root in self.leases.values():
            if expires_at > now:
                wanted.update(screens)
                if preview_root:
                    demand(preview_root, 500)
        for identifier in wanted & self.screen_demands.keys():
            rate, tags = self.screen_demands[identifier]
            for tag in tags:
                demand(tag, rate)
        for alarm in project.get('alarms', []):
            if alarm['enabled']:
                demand(alarm['tag'], 250)
        for tag, rate in self.trend_demands.items():
            demand(tag, rate)
        for history in project.get('historian', {}).get('tags', []):
            demand(history['tag'], history['sample_ms'])
        for command in project.get('commands', []):
            demand(command['root_tag'], command['update_ms'])
        return rates
