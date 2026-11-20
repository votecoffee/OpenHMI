"""Logical tag definitions, UDT aliases and local initialization.

The driver holds its existing state/configuration locks while configuring this
catalog. It owns no connections, workers or locks and performs no transport I/O.
Cached aliases and local values are reconciled in the caller's same transaction.
"""
from copy import deepcopy


class TagCatalog:
    def __init__(self):
        self.definitions = {}
        self.sources = {}
        self.address_aliases = {}
        self.local_names = set()

    def configure(self, tags, changed_connections, sample_cache, local_values):
        old = self.definitions
        self.definitions = {tag['name']: deepcopy(tag) for tag in tags}
        for name in self.local_names - self.definitions.keys():
            local_values.pop(name, None)
        self.local_names = {name for name, tag in self.definitions.items() if not tag['connection']}
        self.sources = {}
        for name, tag in self.definitions.items():
            self.sources[name] = (name, '')
            for member in tag['members']:
                self.sources[f'{name}.{member}'] = (name, member)
            if old.get(name) != tag or tag['connection'] in changed_connections:
                for alias, (root, _) in self.sources.items():
                    if root == name:
                        sample_cache.samples.pop(alias, None)
                if not tag['connection']:
                    local_values[name] = float(tag['initial']) if tag['type'] == 'number' else deepcopy(tag['initial'])
                else:
                    local_values.pop(name, None)
        self.address_aliases = {}
        for alias, (root, member) in self.sources.items():
            tag = self.definitions[root]
            if tag['connection']:
                key = (tag['connection'], tag['address'])
                self.address_aliases.setdefault(key, []).append((alias, tag, member))
