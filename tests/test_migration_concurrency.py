"""Durable migration intent and cancellation must preserve file/DB agreement."""

import asyncio
import threading
from unittest.mock import AsyncMock

import pytest

from mcontrol.domain import migration
from mcontrol.infra import db, db_async, server_lock
from mcontrol.services import server_service
from tests.test_migration import _VARS, _legacy_layout


async def test_cancelled_migration_keeps_lock_until_database_thread_finishes(tmp_path, monkeypatch):
    server_dir = _legacy_layout(tmp_path)
    entered = threading.Event()
    release = threading.Event()
    observed = {'name': 'atm10', 'dir': str(server_dir), 'scaffolded_at': None, 'variables': {}}

    def slow_commit(*, name, variables):
        entered.set()
        assert release.wait(5), 'test failed to release fake DB write'
        observed.update(scaffolded_at='committed', variables=variables)

    monkeypatch.setattr(db, 'complete_migration', slow_commit)
    monkeypatch.setattr(db_async, 'get_server', AsyncMock(side_effect=lambda name: dict(observed)))

    async def run():
        async with server_lock.server_mutation_lock(tmp_path, '__fleet__'):
            await server_service.migrate_legacy_server(
                name='atm10', variables=_VARS, server_dir=server_dir
            )

    async def next_mutation():
        async with server_lock.server_mutation_lock(tmp_path, '__fleet__'):
            return 'acquired'

    operation = asyncio.create_task(run())
    contender = None
    try:
        assert await asyncio.to_thread(entered.wait, 3)
        operation.cancel()
        contender = asyncio.create_task(next_mutation())
        await asyncio.sleep(0.05)
        assert not operation.done()
        assert not contender.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await operation
        assert await asyncio.wait_for(contender, 3) == 'acquired'
        assert 'image: eclipse-temurin' in (server_dir / 'docker-compose.yml').read_text()
        assert not (server_dir / 'Dockerfile').exists()
        assert observed['scaffolded_at'] is not None
        server_service.ensure_no_pending_migration(observed)
        assert migration.latest_recoverable_backup(server_dir) is None
    finally:
        release.set()
        await asyncio.gather(operation, *([contender] if contender else []), return_exceptions=True)


async def test_uncertain_write_retries_same_intent_without_restoring_files(tmp_path, monkeypatch):
    server_dir = _legacy_layout(tmp_path)
    row = {'name': 'atm10', 'dir': str(server_dir), 'scaffolded_at': None, 'variables': {}}
    calls = []

    async def attempt(*, name, variables):
        calls.append(dict(variables))
        if len(calls) == 1:
            raise TimeoutError('response lost')
        row.update(scaffolded_at='committed', variables=variables)

    monkeypatch.setattr(db_async, 'complete_migration', attempt)
    monkeypatch.setattr(db_async, 'get_server', AsyncMock(side_effect=lambda name: dict(row)))
    with pytest.raises(migration.MigrationError):
        await server_service.migrate_legacy_server(
            name='atm10', variables=_VARS, server_dir=server_dir
        )
    backup = migration.latest_recoverable_backup(server_dir)
    converted = (server_dir / 'docker-compose.yml').read_bytes()
    assert backup is not None
    assert not (server_dir / 'Dockerfile').exists()
    with pytest.raises(migration.MigrationError, match='saved values'):
        await server_service.migrate_legacy_server(
            name='atm10', variables={**_VARS, 'server_jar': 'different.jar'}, server_dir=server_dir
        )
    assert (server_dir / 'docker-compose.yml').read_bytes() == converted
    assert len(calls) == 1
    await server_service.migrate_legacy_server(name='atm10', variables=_VARS, server_dir=server_dir)
    assert calls == [_VARS, _VARS]
    assert (server_dir / 'docker-compose.yml').read_bytes() == converted
    assert migration.latest_recoverable_backup(server_dir) is None
    assert len(list(server_dir.glob('.mcontrol-migration-backup-*'))) == 1


def test_pending_marker_with_mismatched_database_values_blocks_lifecycle(tmp_path):
    server_dir = _legacy_layout(tmp_path)
    backup = migration.migrate('atm10', _VARS, server_dir)
    with pytest.raises(migration.MigrationError):
        server_service.ensure_no_pending_migration({
            'name': 'atm10', 'dir': str(server_dir), 'scaffolded_at': 'committed',
            'variables': {**_VARS, 'server_jar': 'wrong.jar'},
        })
    assert migration.latest_recoverable_backup(server_dir) == backup


async def test_repeated_cancellation_of_binding_write_holds_fleet_lock(tmp_path, monkeypatch):
    entered = threading.Event()
    release = threading.Event()
    finished = threading.Event()

    def write_binding(**kwargs):
        entered.set()
        assert release.wait(5)
        finished.set()

    monkeypatch.setattr(db, 'update_bindings', write_binding)

    async def mutate():
        async with server_lock.server_mutation_lock(tmp_path, '__fleet__'):
            await db_async.update_bindings(name='alias', container_name='atm10', dir='bound')

    operation = asyncio.create_task(mutate())
    try:
        assert await asyncio.to_thread(entered.wait, 3)
        operation.cancel()
        await asyncio.sleep(0.01)
        operation.cancel()
        await asyncio.sleep(0.01)
        assert not operation.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await operation
        assert finished.is_set()
    finally:
        release.set()
        await asyncio.gather(operation, return_exceptions=True)


async def test_lifecycle_cancellation_drains_started_operation_before_unlock(tmp_path):
    entered = asyncio.Event()
    release = asyncio.Event()
    finished = asyncio.Event()

    async def lifecycle_action():
        entered.set()
        await release.wait()
        finished.set()
        return 'running'

    async def mutate():
        async with server_lock.server_mutation_lock(tmp_path, '__fleet__'):
            await server_lock.drain_on_cancel(lifecycle_action())

    operation = asyncio.create_task(mutate())
    try:
        await asyncio.wait_for(entered.wait(), 3)
        operation.cancel()
        await asyncio.sleep(0.01)
        operation.cancel()
        await asyncio.sleep(0.01)
        assert not operation.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await operation
        assert finished.is_set()
    finally:
        release.set()
        await asyncio.gather(operation, return_exceptions=True)


async def test_advisory_lock_serializes_separate_processes(tmp_path):
    import subprocess
    import sys

    script = '''
import asyncio
import sys
from pathlib import Path
from mcontrol.infra.server_lock import server_mutation_lock
async def main():
    print('ready', flush=True)
    async with server_mutation_lock(Path(sys.argv[1]), '__fleet__'):
        print('acquired', flush=True)
asyncio.run(main())
'''
    child = None
    try:
        async with server_lock.server_mutation_lock(tmp_path, '__fleet__'):
            child = subprocess.Popen(
                [sys.executable, '-c', script, str(tmp_path)],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW')
                else 0,
            )
            assert await asyncio.wait_for(asyncio.to_thread(child.stdout.readline), 5) == 'ready\n'
            await asyncio.sleep(0.1)
            assert child.poll() is None
        output, error = await asyncio.to_thread(child.communicate, timeout=5)
        assert child.returncode == 0, error
        assert output == 'acquired\n'
    finally:
        if child is not None and child.poll() is None:
            child.kill()
            child.wait(timeout=5)


def test_retry_form_does_not_restore_cleared_jvm_arguments(tmp_path):
    from mcontrol.routes.migrate import _initial_form

    server_dir = _legacy_layout(tmp_path)
    variables = {key: value for key, value in _VARS.items() if key != 'jvm_extra_args'}
    variables['java_version'] = 25
    migration.migrate('atm10', variables, server_dir)
    form = _initial_form({
        'name': 'atm10', 'dir': str(server_dir),
        'variables': {'jvm_extra_args': '-Dold=setting', 'java_version': 17},
    })
    assert form['jvm_extra_args'] == ''
    assert form['java_version'] == 25
    from mcontrol.domain.server_variables_form import build_variables

    assert build_variables(form) == variables
