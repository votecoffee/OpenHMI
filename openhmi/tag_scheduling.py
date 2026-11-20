"""Physical rate/deadline policy; caller holds RuntimeDriver.lock throughout.

This component owns scheduling maps but performs no transport calls and owns no
locks or workers. Freshness tightening is applied to the supplied sample cache
inside the same caller-controlled state transaction.
"""
from collections import defaultdict
from .tag_values import freshness_seconds

BAD_TAG_RETRY_SECONDS = 30


class ScanSchedule:
    def __init__(self):
        self.deadlines = {}
        self.rates = {}
        self.refresh_after = {}
        self.bad_retry_at = {}
        self.demanded_aliases = {}

    def reconcile(self, demands, now, sources, definitions, address_aliases, sample_cache):
        grouped = {}
        demanded_aliases = defaultdict(dict)
        for alias, rate in demands.items():
            root, _ = sources.get(alias, (None, ''))
            tag = definitions.get(root)
            if tag and tag['connection']:
                key = (tag['connection'], tag['address'])
                grouped[key] = min(rate, grouped.get(key, rate))
                demanded_aliases[tag['connection']][alias] = key
                if alias not in self.demanded_aliases.get(tag['connection'], {}):
                    self.bad_retry_at.pop(key, None)
        for key, previous_rate in self.rates.items():
            rate = grouped.get(key)
            if rate is None:
                self.deadlines.pop(key, None)
                self.refresh_after.pop(key, None)
                self.bad_retry_at.pop(key, None)
            elif rate < previous_rate:
                self.deadlines[key] = now
                # Tighten the existing samples without letting slower demand revive them.
                for alias, _, _ in address_aliases[key]:
                    sample_cache.tighten_rate(alias, rate)
            elif rate > previous_rate and self.deadlines.get(key, now) > now:
                # Only defer a scheduled read. Leave already-due refreshes intact.
                alias = address_aliases[key][0][0]
                timing = sample_cache.timing(alias)
                if timing is not None:
                    recorded_rate, acquired = timing
                    interval = min(rate / 1000, freshness_seconds(recorded_rate))
                    self.deadlines[key] = max(self.deadlines[key], acquired + interval)
        for key in grouped.keys() - self.rates.keys():
            self.refresh_after[key] = now
        self.rates = grouped
        self.demanded_aliases = demanded_aliases

    def due_addresses(self, identifier, now, has_usable_data):
        due = {address: self.deadlines.get((route, address), 0) for route, address in self.rates
               if route == identifier and now >= self.deadlines.get((route, address), 0)}
        if not self.bad_retry_at or not any((identifier, address) in self.bad_retry_at for address in due):
            return due
        if not has_usable_data():
            return due
        effective = {address: max(deadline, self.bad_retry_at.get((identifier, address), 0))
                     for address, deadline in due.items()}
        return {address: deadline for address, deadline in effective.items() if now >= deadline}

    def reset_route(self, identifier):
        for schedule in (self.deadlines, self.bad_retry_at):
            for key in list(schedule):
                if key[0] == identifier:
                    del schedule[key]

    def accept_receipt(self, key, acquired, scan_finished):
        rate = self.rates.get(key)
        if rate is None:
            return None
        refresh_after = self.refresh_after.get(key)
        if refresh_after is not None:
            # Discard a reply received before this address came back into demand.
            if acquired < refresh_after:
                return None
            del self.refresh_after[key]
        pending_deadline = self.deadlines.get(key)
        # A sample received before a faster demand arrived cannot satisfy its refresh.
        if pending_deadline is None or pending_deadline <= acquired:
            self.deadlines[key] = scan_finished + rate / 1000
        return rate

    def record_outcome(self, key, usable_address, scan_finished):
        if usable_address:
            self.bad_retry_at.pop(key, None)
        else:
            self.bad_retry_at[key] = scan_finished + BAD_TAG_RETRY_SECONDS
