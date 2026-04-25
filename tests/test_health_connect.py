"""Модульные тесты: health_connect (десктопные заглушки)."""

import pytest
import sys
import types
from unittest.mock import patch


@patch('health_connect.ANDROID', False)
def test_is_available_desktop():
    """На десктопе HC недоступен."""
    import health_connect as hc
    assert hc.is_available() is False


@patch('health_connect.ANDROID', False)
def test_has_read_permissions_desktop():
    """На десктопе разрешения HC не выданы."""
    import health_connect as hc
    assert hc.has_read_permissions() is False


@patch('health_connect.ANDROID', False)
def test_sync_from_hc_desktop(tmp_db):
    """sync_from_hc вызывает on_done(False, ...) на десктопе."""
    import health_connect as hc
    results = []
    hc.sync_from_hc(tmp_db, days=7, on_done=lambda ok, msg: results.append((ok, msg)))
    assert len(results) == 1
    assert results[0][0] is False


@patch('health_connect.ANDROID', False)
def test_sync_from_hc_blocking_desktop(tmp_db):
    """Блокирующая синхронизация возвращает False на десктопе."""
    import health_connect as hc
    ok, msg = hc.sync_from_hc_blocking(tmp_db, context=None, days=1)
    assert ok is False


def test_merge_steps_to_db(db_with_metrics):
    """_merge_steps_to_db корректно записывает шаги в БД."""
    import health_connect as hc

    steps_by_day = {
        '2026-04-01': 8000,
        '2026-04-02': 5000,
        '2026-04-03': 0,      # <= 0, пропускается
    }

    merged, total = hc._merge_steps_to_db(db_with_metrics, steps_by_day)
    assert total == 3
    assert merged == 2  # 2 из 3 (третий 0 шагов — пропущен)

    s1, _, _ = db_with_metrics.get_activity_for_date('2026-04-01')
    assert s1 == 8000

    s3, _, _ = db_with_metrics.get_activity_for_date('2026-04-03')
    assert s3 == 0  # не обновлён


def test_merge_respects_existing_higher(db_with_metrics):
    """_merge_steps_to_db не перезаписывает, если в БД больше шагов."""
    import health_connect as hc
    db = db_with_metrics

    # Записываем 10000 шагов напрямую
    db.update_day_activity('2026-04-05', 10000, 7.0, 450.0)

    # HC пытается записать меньше
    steps_by_day = {'2026-04-05': 5000}
    merged, total = hc._merge_steps_to_db(db, steps_by_day)
    assert merged == 0  # не перезаписано

    s, _, _ = db.get_activity_for_date('2026-04-05')
    assert s == 10000


def test_is_suspended_none():
    """_is_suspended(None) → False."""
    import health_connect as hc
    assert hc._is_suspended(None) is False


def test_is_suspended_object():
    """_is_suspended с обычным объектом → False."""
    import health_connect as hc
    assert hc._is_suspended("hello") is False


def test_hc_read_permissions_list():
    """Проверяем что список разрешений непустой."""
    import health_connect as hc
    assert len(hc.HC_READ_PERMISSIONS) > 0
    assert 'android.permission.health.READ_STEPS' in hc.HC_READ_PERMISSIONS
