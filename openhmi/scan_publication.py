"""Publish scan receipts under the existing route and runtime state locks.

The driver must reject obsolete project generations before calling. There is no
socket I/O, worker submission or lock acquisition in this publication function.
"""
from .tag_values import freshness_seconds


def publish_scan_receipts(identifier, connection, due, results, scan_finished, *,
                          schedule, sample_cache, address_aliases):
    awaiting_usable = not connection.has_usable_sample or connection.outage_started is not None
    demanded_aliases = schedule.demanded_aliases.get(identifier, {})
    for address, (result, acquired, timestamp) in zip(due, results):
        key = (identifier, address)
        rate = schedule.accept_receipt(key, acquired, scan_finished)
        if rate is None:
            continue
        usable_address = False
        for alias, tag, member in address_aliases[key]:
            sample = sample_cache.decode(result, tag, member)
            sample_cache.publish(alias, sample, timestamp, acquired, rate, connection.failure_generation)
            # One physical UDT read can populate aliases no consumer requested.
            if alias in demanded_aliases and sample['quality'] == 'good':
                usable_address = True
                if awaiting_usable and scan_finished - acquired <= freshness_seconds(rate):
                    connection.has_usable_sample = True
                    awaiting_usable = False
                    if connection.outage_started is not None:
                        connection.timings.record('recovery', scan_finished - connection.outage_started)
                        connection.outage_started = None
        schedule.record_outcome(key, usable_address, scan_finished)
