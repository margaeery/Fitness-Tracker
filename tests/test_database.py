"""Модульные тесты: FitnessDB."""

import pytest
from datetime import datetime, timedelta


class TestCreateTables:
    """Проверяем, что все таблицы создаются."""

    def test_tables_exist(self, tmp_db):
        cursor = tmp_db.conn.cursor()
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row[0] for row in cursor.fetchall()}
        assert 'daily_activity' in tables
        assert 'user_metrics' in tables
        assert 'sensor_state' in tables
        assert 'goal_state' in tables


class TestUserMetrics:
    """Тесты сохранения/чтения метрик пользователя."""

    def test_save_and_get(self, tmp_db):
        tmp_db.save_user_metrics(75.0, 180.0, 8000)
        m = tmp_db.get_latest_metrics()
        assert m is not None
        assert m[0] == 75.0    # weight
        assert m[1] == 180.0   # height
        assert m[2] == 8000    # goal

    def test_no_metrics_returns_none(self, tmp_db):
        assert tmp_db.get_latest_metrics() is None

    def test_update_metrics(self, tmp_db):
        tmp_db.save_user_metrics(70.0, 170.0, 5000)
        tmp_db.save_user_metrics(72.0, 170.0, 6000)
        m = tmp_db.get_latest_metrics()
        assert m[0] == 72.0
        assert m[2] == 6000

    def test_goal_change_resets_achieved(self, tmp_db):
        tmp_db.save_user_metrics(70.0, 170.0, 5000)
        today = datetime.now().strftime('%Y-%m-%d')
        tmp_db.set_goal_achieved(today)
        assert tmp_db.get_goal_achieved(today) is True
        # Меняем цель
        tmp_db.save_user_metrics(70.0, 170.0, 8000)
        assert tmp_db.get_goal_achieved(today) is False


class TestDailyActivity:
    """Тесты работы с daily_activity."""

    def test_get_today_steps_empty(self, tmp_db):
        assert tmp_db.get_today_steps() == 0

    def test_add_steps(self, tmp_db):
        tmp_db.add_steps(100)
        assert tmp_db.get_today_steps() == 100
        tmp_db.add_steps(200)
        assert tmp_db.get_today_steps() == 300

    def test_update_day_activity(self, tmp_db):
        date = '2026-04-01'
        tmp_db.update_day_activity(date, 5000, 3.5, 200.0)
        steps, dist, kcal = tmp_db.get_activity_for_date(date)
        assert steps == 5000
        assert dist == 3.5
        assert kcal == 200.0

    def test_update_day_replaces(self, tmp_db):
        date = '2026-04-01'
        tmp_db.update_day_activity(date, 3000, 2.0, 100.0)
        tmp_db.update_day_activity(date, 8000, 5.5, 300.0)
        steps, _, _ = tmp_db.get_activity_for_date(date)
        assert steps == 8000

    def test_get_activity_missing_date(self, tmp_db):
        steps, dist, kcal = tmp_db.get_activity_for_date('2099-01-01')
        assert steps == 0
        assert dist == 0.0
        assert kcal == 0.0

    def test_get_data_for_range(self, db_with_activity):
        labels, data = db_with_activity.get_data_for_range(
            '2026-04-01', '2026-04-07')
        assert len(labels) == 7
        assert len(data['steps']) == 7
        assert data['steps'][0] == 5000
        assert data['steps'][6] == 11000

    def test_get_data_for_range_empty(self, tmp_db):
        labels, data = tmp_db.get_data_for_range('2099-01-01', '2099-01-07')
        assert labels == []
        assert data['steps'] == []

    def test_get_year_data(self, db_with_activity):
        labels, data = db_with_activity.get_year_data_for_specific_year(2026)
        assert len(labels) == 12
        assert len(data['steps']) == 12
        # Апрель = индекс 3, должен иметь данные
        assert data['steps'][3] > 0
        # Январь = индекс 0, пустой
        assert data['steps'][0] == 0


class TestSensorState:
    """Тесты для baseline датчика шагов."""

    def test_no_baseline(self, tmp_db):
        assert tmp_db.get_sensor_baseline('2026-04-01') is None

    def test_save_and_get_baseline(self, tmp_db):
        tmp_db.save_sensor_baseline('2026-04-01', 12345)
        assert tmp_db.get_sensor_baseline('2026-04-01') == 12345

    def test_update_baseline(self, tmp_db):
        tmp_db.save_sensor_baseline('2026-04-01', 100)
        tmp_db.save_sensor_baseline('2026-04-01', 500)
        assert tmp_db.get_sensor_baseline('2026-04-01') == 500

    def test_delete_baseline(self, tmp_db):
        tmp_db.save_sensor_baseline('2026-04-01', 100)
        tmp_db.delete_sensor_baseline('2026-04-01')
        assert tmp_db.get_sensor_baseline('2026-04-01') is None


class TestGoalState:
    """Тесты для отслеживания достижения цели."""

    def test_goal_not_achieved(self, tmp_db):
        assert tmp_db.get_goal_achieved('2026-04-01') is False

    def test_set_goal_achieved(self, tmp_db):
        tmp_db.set_goal_achieved('2026-04-01')
        assert tmp_db.get_goal_achieved('2026-04-01') is True

    def test_reset_goal(self, tmp_db):
        tmp_db.set_goal_achieved('2026-04-01')
        tmp_db.reset_goal_achieved('2026-04-01')
        assert tmp_db.get_goal_achieved('2026-04-01') is False


class TestClose:
    """Тесты закрытия БД."""

    def test_close_no_error(self, tmp_db):
        tmp_db.close()
        # После close повторный close или операции не должны крашить тест
