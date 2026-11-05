"""Kill and restart an offline OpenHMI process after a lost command response."""

import argparse
import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timezone
from http.client import RemoteDisconnected
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.request import build_opener, ProxyHandler, Request
from uuid import uuid4

from fastapi import HTTPException, Request as ASGIRequest
import uvicorn

from openhmi.projects import ProjectStore
from offline_runtime_fixture import OfflinePlant, open_runtime, project_fixture, require

DATABASE = 'Crash.openhmi.sqlite3'
WRITES = 'synthetic-plc-writes.jsonl'
CONTROL = '/api/controls/soak/activate'
DRILL_HEADER = 'X-OpenHMI-Drill-Token'


def read_writes(work):
    path = work / WRITES
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]


class PersistentPlant(OfflinePlant):
    def __init__(self, work):
        super().__init__()
        self.receipts = work / WRITES
        for sequence in read_writes(work):
            super().record_write(sequence)

    def record_write(self, sequence):
        with self.receipts.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(sequence) + '\n')
            stream.flush()
            os.fsync(stream.fileno())
        super().record_write(sequence)


def serve(args):
    require((args.work / 'fixture-token').read_text(encoding='ascii') == args.token,
            'Child requires a runner-created fixture directory')
    plant = PersistentPlant(args.work)
    with patch('pycomm3.LogixDriver', side_effect=AssertionError('Physical PLC access is disabled for the drill')):
        app = open_runtime(args.work / DATABASE, plant)

        @app.middleware('http')
        async def hold_response(request: ASGIRequest, call_next):
            response = await call_next(request)
            if (args.child == 'before' and request.url.path == CONTROL
                    and request.headers.get(DRILL_HEADER) == args.token
                    and response.status_code == 200):
                (args.work / 'response-held').touch()
                await asyncio.Event().wait()
            return response

        def authorize(request):
            if request.headers.get(DRILL_HEADER) != args.token:
                raise HTTPException(403, 'Fixture token required')

        @app.post('/__drill/complete/{sequence}')
        def complete(sequence: int, request: ASGIRequest):
            authorize(request)
            plant.finish_command(sequence)
            return {'ok': True}

        @app.post('/__drill/stop')
        def stop(request: ASGIRequest):
            authorize(request)
            server.should_exit = True
            return {'ok': True}

        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            listener.listen()
            server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', access_log=False, lifespan='on'))
            (args.work / f'{args.child}.port').write_text(str(listener.getsockname()[1]), encoding='ascii')
            server.run(sockets=[listener])


def request(port, path, data=None, *, headers=None, expected=200, timeout=3, method=None):
    opener = build_opener(ProxyHandler({}))
    payload = json.dumps(data).encode() if data is not None else None
    query = Request(f'http://127.0.0.1:{port}{path}', data=payload,
                    headers={'Content-Type': 'application/json', **(headers or {})}, method=method)
    try:
        response = opener.open(query, timeout=timeout)
    except HTTPError as error:
        response = error
    with response:
        require(response.status == expected, f'{path} returned HTTP {response.status}; expected {expected}')
        return json.load(response)


def until(process, probe, label, timeout):
    started = time.monotonic()
    while time.monotonic() - started < timeout:
        require(process.poll() is None, f'Runtime exited while waiting for {label}')
        result = probe()
        if result:
            return result
        time.sleep(0.05)
    raise RuntimeError(f'Timed out waiting for {label}')


@contextmanager
def child(work, phase, token, timeout):
    with (work / f'{phase}.log').open('wb') as log:
        process = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), '--work', str(work), '--child', phase, '--token', token],
            stdout=log, stderr=subprocess.STDOUT, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
        )
        try:
            def ready():
                try:
                    port = int((work / f'{phase}.port').read_text(encoding='ascii'))
                    return port, request(port, '/api/project/active', timeout=0.5)
                except (OSError, ValueError):
                    return None

            port, active = until(process, ready, 'runtime readiness', timeout)
            yield process, port, active
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=timeout)


def fresh_command(port):
    sample = request(port, '/api/tags')['samples'].get('SoakCommand', {})
    return sample.get('quality') == 'good'


def drill(work, timeout, report):
    token = uuid4().hex
    (work / 'fixture-token').write_text(token, encoding='ascii')
    ProjectStore(work / DATABASE, initial_project=project_fixture()).close()

    headers = {DRILL_HEADER: token}
    with child(work, 'before', token, timeout) as (process, port, _):
        report['original_pid'] = process.pid
        state = request(port, '/api/project')
        draft = state['draft']
        draft['title'] = 'Applied before the process termination'
        saved = request(port, '/api/project/draft', {'project': draft, 'expected_revision': state['draft_revision']},
                        method='PUT')
        request(port, '/api/project/apply', {'expected_revision': saved['draft_revision']})
        active = request(port, '/api/project/active')
        report['applied_revision'] = active['revision']
        until(process, lambda: fresh_command(port), 'good synthetic command sample', timeout)
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(request, port, CONTROL, {},
                                  headers=headers, timeout=timeout + 3)

            def dispatched():
                if pending.done():
                    pending.result()
                    raise RuntimeError('Command response was delivered before the crash')
                if not (work / 'response-held').exists():
                    return None
                items = request(port, '/api/commands?state=unresolved')['items']
                return next((item for item in items if item['state'] == 'requested'), None)

            command = until(process, dispatched, 'persisted request and held HTTP response', timeout)
            sequence = command['sequence']
            require(read_writes(work) == [sequence], 'Expected one durable synthetic write before termination')
            report.update(transaction_id=command['id'], operation_id=command['operation_id'], sequence=sequence)
            require(not pending.done(), 'Operator received the response before termination')
            process.kill()
            report['forced_exit_code'] = process.wait(timeout=timeout)
            require(report['forced_exit_code'] != 0, 'Runtime did not report forced termination')
            try:
                pending.result(timeout=timeout)
            except URLError as error:
                require(not isinstance(error.reason, TimeoutError), 'Operator request timed out before loss was observed')
            except (RemoteDisconnected, ConnectionResetError):
                pass
            else:
                raise RuntimeError('Operator received a command response after forced termination')
            report['operator_response_lost'] = True

    started = time.monotonic()
    with child(work, 'after', token, timeout) as (process, port, reopened):
        report.update(restarted_pid=process.pid, restart_ready_seconds=round(time.monotonic() - started, 3))
        require(reopened['project_instance'] != active['project_instance']
                and reopened['revision'] == active['revision'] and reopened['project'] == active['project'],
                'Applied project did not survive restart')
        report['applied_revision_preserved'] = True
        until(process, lambda: fresh_command(port), 'fresh synthetic data after restart', timeout)
        transaction = f"/api/commands/{command['id']}"
        restored = request(port, transaction)
        require(restored['state'] == 'uncertain' and read_writes(work) == [sequence],
                'Pending transaction was lost or replayed during restart')
        report['state_after_restart'] = restored['state']
        request(port, CONTROL, {}, expected=409)
        require(read_writes(work) == [sequence], 'Duplicate submission caused another write')
        report['duplicate_dispatch_blocked'] = True
        journal = request(port, f"/api/activity?search={command['operation_id']}")['items']
        require(any(item['operation_id'] == command['operation_id'] for item in journal), 'Activity record was lost')
        report['activity_preserved'] = True
        request(port, f'/__drill/complete/{sequence}', {}, headers=headers)
        until(process, lambda: request(port, transaction)['state'] == 'completed',
              'PLC-owned reconciliation', timeout)
        require(read_writes(work) == [sequence], 'Reconciliation replayed the command')
        report.update(reconciled=True, synthetic_writes=1)
        request(port, '/__drill/stop', {}, headers=headers)
        report['restart_shutdown_exit_code'] = process.wait(timeout=timeout)
        require(report['restart_shutdown_exit_code'] == 0, 'Restarted runtime did not shut down cleanly')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work', type=Path, required=True, help='New evidence folder')
    parser.add_argument('--timeout', type=int, default=15, help='Seconds per phase')
    parser.add_argument('--child', choices=('before', 'after'), help=argparse.SUPPRESS)
    parser.add_argument('--token', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.child:
        return serve(args)
    if not 5 <= args.timeout <= 60:
        parser.error('Use a timeout between 5 and 60 seconds.')
    args.work = args.work.resolve()
    try:
        args.work.mkdir(parents=True, exist_ok=False)
    except OSError as error:
        parser.exit(1, f'Cannot create new evidence folder: {error}\n')
    report = {'status': 'failed', 'started_utc': datetime.now(timezone.utc).isoformat(),
              'scope': 'loopback HTTP, forced process exit, synthetic PLC', 'phase_timeout_seconds': args.timeout}
    try:
        drill(args.work, args.timeout, report)
        report['status'] = 'passed'
    except (Exception, KeyboardInterrupt) as error:
        report['error'] = f'{type(error).__name__}: {error}'
    output = json.dumps(report, indent=2, allow_nan=False)
    (args.work / 'report.json').write_text(output + '\n', encoding='utf-8')
    print(output)
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
