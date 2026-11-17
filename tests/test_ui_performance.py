from unittest.mock import Mock

import pytest

from mori.core import AppError
from mori.ui_performance import UIStore, fetch_accounts


def test_cached_settings_are_isolated_expire_and_do_not_hide_fetch_errors():
    now = [0]
    source = Mock()
    source.settings.return_value = ({'rules': []}, 'old')
    ui = UIStore(source, clock=lambda: now[0])
    ui.settings()[0]['rules'].append('local edit')
    assert ui.settings() == ({'rules': []}, 'old')
    assert source.settings.call_count == 1
    now[0] = 31
    source.settings.side_effect = AppError('offline')
    with pytest.raises(AppError):
        ui.settings()
    assert 'settings.json' not in ui.cache


def test_write_refreshes_snapshot_and_conflict_invalidates_it():
    source = Mock()
    source.settings.return_value = ({'rules': []}, 'old')
    source.write.return_value = 'new'
    ui = UIStore(source)
    ui.settings()
    ui.write('settings.json', {'rules': ['saved']}, 'old')
    assert ui.settings() == ({'rules': ['saved']}, 'new')
    assert source.settings.call_count == 1
    source.write.side_effect = AppError('conflict')
    with pytest.raises(AppError):
        ui.write('settings.json', {}, 'new')
    assert 'settings.json' not in ui.cache


def test_runtime_lock_reads_and_writes_always_reach_storage():
    source = Mock()
    ui = UIStore(source)
    ui.runtime()
    ui.runtime()
    ui.read('runner-lock.json', {})
    ui.read('runner-lock.json', {})
    assert source.runtime.call_count == source.read.call_count == 2
    ui.read('credentials.encrypted.json', {})
    ui.read('credentials.encrypted.json', {})
    assert source.read.call_count == 3
    ui.clear()
    ui.read('credentials.encrypted.json', {})
    assert source.read.call_count == 4


def test_account_fetches_overlap_preserve_order_and_keep_failed_accounts_separate():
    from threading import Barrier
    barrier = Barrier(2)
    def fetch(account):
        barrier.wait(timeout=3)
        if account['name'] == 'failed':
            raise AppError('API unavailable')
        return {'account': account['name'], 'rows': [1]}
    reports, errors = fetch_accounts([{'name': 'ok'}, {'name': 'failed'}], fetch)
    assert reports == [{'account': 'ok', 'rows': [1]}]
    assert errors == ['failed：API unavailable']
