"""conftest.py — общие фикстуры для всех тестов."""

import sys
import os
import types
import pytest

# ─── Добавляем корень проекта в sys.path ──────────────────────────────
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# ─── Мок андроид-модулей, которых нет на десктопе ─────────────────────
# Создаём заглушки ДО импорта модулей проекта.

_android_mod = types.ModuleType('android')
_android_storage = types.ModuleType('android.storage')
_android_perms = types.ModuleType('android.permissions')

_android_storage.app_storage_path = lambda: os.path.join(
    PROJECT_ROOT, 'tests', '_test_data')
_android_perms.check_permission = lambda p: False
_android_perms.request_permissions = lambda perms, cb=None: None

_android_mod.storage = _android_storage
_android_mod.permissions = _android_perms

# jnius — всегда «не Android» для юнит-тестов
from unittest.mock import MagicMock as _MagicMock

_jnius = types.ModuleType('jnius')
_jnius.autoclass = lambda name: _MagicMock(name=name)
_jnius.PythonJavaClass = type('PythonJavaClass', (), {})
_jnius.java_method = lambda *a, **k: lambda f: f

# Не подставляем, если уже есть реальный (маловероятно на десктопе)
for mod_name, mod_obj in [
    ('android', _android_mod),
    ('android.storage', _android_storage),
    ('android.permissions', _android_perms),
    ('jnius', _jnius),
]:
    sys.modules.setdefault(mod_name, mod_obj)


# ─── Фикстуры ────────────────────────────────────────────────────────

@pytest.fixture
def tmp_db(tmp_path):
    """Создаёт временную базу данных FitnessDB в tmp_path."""
    # Подменяем DB_PATH до импорта
    import database
    original_path = database.DB_PATH
    database.DB_PATH = str(tmp_path)

    db = database.FitnessDB(db_name='test_fitness.db')
    yield db
    db.close()

    database.DB_PATH = original_path


@pytest.fixture
def db_with_metrics(tmp_db):
    """БД с заполненным профилем пользователя."""
    tmp_db.save_user_metrics(70.0, 175.0, 10000)
    return tmp_db


@pytest.fixture
def db_with_activity(db_with_metrics):
    """БД с метриками и данными активности за несколько дней."""
    from datetime import datetime, timedelta
    from calculator import FitnessCalculator

    db = db_with_metrics
    base = datetime(2026, 4, 1)

    for i in range(7):
        date_str = (base + timedelta(days=i)).strftime('%Y-%m-%d')
        steps = 5000 + i * 1000
        dist = FitnessCalculator.calculate_distance(steps, 175.0)
        kcal = FitnessCalculator.calculate_calories(steps, 70.0)
        db.update_day_activity(date_str, steps, dist, kcal)

    return db
