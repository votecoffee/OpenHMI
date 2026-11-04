"""Offline PLC feedback demonstration. Refuses every network-backed root.

Create the local Command UDT and no-code request button described in
docs/command-transactions.md, then bind Python buttons to these feedback actions.
This models the PLC side of the protocol; real PLC logic owns these members.
"""

from copy import deepcopy


def feedback(app, complete=False, result=0):
    driver = app.driver
    with driver.io_lock, driver.lock:
        definition = driver.definitions.get('CycleCommand')
        if not definition or definition['connection'] or definition['type'] != 'struct':
            raise ValueError('This demonstration requires the local CycleCommand UDT')
        values = driver._tags['CycleCommand']
        sequence = values['RequestSequence']
        if type(sequence) is not int or sequence <= 0:
            raise ValueError('Dispatch a request before simulating PLC feedback')
        # Intentionally models PLC-owned memory, outside ordinary HMI tag writes.
        values['AcceptedSequence'] = sequence
        if complete:
            if result == 0 and 'Staging' in values and 'Running' in values:
                values['Running'] = deepcopy(values['Staging'])
            values['ResultCode'] = result
            values['CompletedSequence'] = sequence  # Publish completion last.


def register(app):
    app.register_action('command_accept', 'Simulate PLC acceptance', lambda app: feedback(app))
    app.register_action('command_complete', 'Simulate PLC success', lambda app: feedback(app, True))
    app.register_action('command_fail', 'Simulate PLC rejection (17)', lambda app: feedback(app, True, 17))
