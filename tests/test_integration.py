"""Интеграционные тесты: полный цикл данных через несколько модулей."""

import pytest
import os
from datetime import datetime, timedelta
from calculator import FitnessCalculator


class TestFullDataCycle:
    """Полный цикл: метрики → шаги → расчёт → БД → чтение."""

    def test_save_metrics_then_activity(self, tmp_db):
        """Сохранение метрик, затем активности за день."""
        tmp_db.save_user_metrics(80.0, 180.0, 10000)

        steps = 7500
        metrics = tmp_db.get_latest_metrics()
        w, h, g = metrics
        dist = FitnessCalculator.calculate_distance(steps, h)
        kcal = FitnessCalculator.calculate_calories(steps, w)

        today = datetime.now().strftime('%Y-%m-%d')
        tmp_db.update_day_activity(today, steps, dist, kcal)

        s, d, k = tmp_db.get_activity_for_date(today)
        assert s == 7500
        assert d == dist
        assert k == kcal

    def test_multiple_days_range_query(self, tmp_db):
        """Заполняем 30 дней, читаем через get_data_for_range."""
        tmp_db.save_user_metrics(70.0, 170.0, 8000)
        metrics = tmp_db.get_latest_metrics()
        w, h, g = metrics

        base = datetime(2026, 3, 1)
        for i in range(30):
            d = base + timedelta(days=i)
            date_str = d.strftime('%Y-%m-%d')
            steps = 4000 + i * 200
            dist = FitnessCalculator.calculate_distance(steps, h)
            kcal = FitnessCalculator.calculate_calories(steps, w)
            tmp_db.update_day_activity(date_str, steps, dist, kcal)

        labels, data = tmp_db.get_data_for_range('2026-03-01', '2026-03-30')
        assert len(labels) == 30
        assert data['steps'][0] == 4000
        assert data['steps'][29] == 4000 + 29 * 200

    def test_year_aggregation(self, tmp_db):
        """Годовая агрегация по месяцам."""
        tmp_db.save_user_metrics(70.0, 170.0, 8000)

        # Добавляем по 1 записи в январь и апрель
        tmp_db.update_day_activity('2026-01-15', 5000, 3.0, 150.0)
        tmp_db.update_day_activity('2026-04-10', 8000, 5.0, 300.0)

        labels, data = tmp_db.get_year_data_for_specific_year(2026)
        assert data['steps'][0] == 5000   # январь
        assert data['steps'][3] == 8000   # апрель
        assert data['steps'][6] == 0      # июль


class TestHCMergeIntegration:
    """Интеграция HC merge с БД и калькулятором."""

    def test_hc_merge_creates_activity(self, db_with_metrics):
        """HC merge создаёт записи с правильными dist/kcal."""
        import health_connect as hc

        steps_by_day = {
            '2026-04-08': 12000,
            '2026-04-09': 6000,
        }
        merged, total = hc._merge_steps_to_db(db_with_metrics, steps_by_day)
        assert merged == 2

        s, d, k = db_with_metrics.get_activity_for_date('2026-04-08')
        assert s == 12000
        # Проверяем, что dist и kcal рассчитаны правильно
        expected_dist = FitnessCalculator.calculate_distance(12000, 175.0)
        expected_kcal = FitnessCalculator.calculate_calories(12000, 70.0)
        assert d == expected_dist
        assert k == expected_kcal

    def test_hc_merge_updates_only_higher(self, db_with_metrics):
        """HC merge обновляет только если HC > local."""
        db = db_with_metrics
        db.update_day_activity('2026-04-08', 8000, 5.0, 300.0)

        import health_connect as hc
        # HC с бо́льшим значением
        merged, _ = hc._merge_steps_to_db(db, {'2026-04-08': 10000})
        assert merged == 1
        s, _, _ = db.get_activity_for_date('2026-04-08')
        assert s == 10000

        # HC с меньшим значением
        merged, _ = hc._merge_steps_to_db(db, {'2026-04-08': 5000})
        assert merged == 0
        s, _, _ = db.get_activity_for_date('2026-04-08')
        assert s == 10000  # не перезаписано

    def test_hc_merge_today_resets_baseline(self, db_with_metrics):
        """При обновлении сегодняшних шагов сбрасывается baseline."""
        db = db_with_metrics
        today = datetime.now().strftime('%Y-%m-%d')

        db.save_sensor_baseline(today, 50000)
        assert db.get_sensor_baseline(today) == 50000

        import health_connect as hc
        hc._merge_steps_to_db(db, {today: 15000})

        # Baseline должен быть удалён
        assert db.get_sensor_baseline(today) is None


class TestServiceStateIntegration:
    """Интеграция ServiceState с БД."""

    @pytest.fixture
    def state(self, db_with_metrics):
        import service as svc
        db_path = os.path.dirname(db_with_metrics.conn.execute(
            "PRAGMA database_list").fetchone()[2])
        svc.FOREGROUND_FLAG = os.path.join(db_path, '.fg_test')
        svc.HC_SYNC_FLAG = os.path.join(db_path, '.hc_test')
        return svc.ServiceState(db_with_metrics)

    def test_sensor_to_db_roundtrip(self, state):
        """Датчик → state → save_to_db → read DB."""
        state.process_sensor(100000)   # baseline
        state.process_sensor(103000)   # 3000 шагов
        state.save_to_db()

        s, d, k = state.db.get_activity_for_date(state.current_date)
        assert s == 3000
        assert d == FitnessCalculator.calculate_distance(3000, 175.0)
        assert k == FitnessCalculator.calculate_calories(3000, 70.0)

    def test_hc_override_then_sensor(self, state):
        """HC пишет шаги → sensor пересчитывает baseline."""
        state.process_sensor(100000)   # baseline = 100000
        state.process_sensor(100500)   # 500 шагов
        state.save_to_db()

        # HC пишет 10000
        state.db.update_day_activity(state.current_date, 10000, 7.0, 450.0)
        state.process_sensor(100600)  # +600 от baseline, но в БД 10000
        state.save_to_db()

        # save_to_db видит что db_steps (10000) > state.steps (600) → принимает HC
        s, _, _ = state.db.get_activity_for_date(state.current_date)
        assert s == 10000

    def test_midnight_saves_old_day(self, state):
        """При смене дня: старый день сохранён, новый — чистый."""
        from unittest.mock import patch

        state.process_sensor(100000)
        state.process_sensor(105000)  # 5000 шагов

        old_date = state.current_date
        new_date = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')

        state.current_date = old_date
        with patch('service.datetime') as mock_dt:
            mock_dt.now.return_value = datetime.now() + timedelta(days=1)
            mock_dt.side_effect = lambda *a, **k: datetime(*a, **k)
            state.handle_midnight()

        # Старый день сохранён
        s, _, _ = state.db.get_activity_for_date(old_date)
        assert s == 5000

        # Новый день чистый
        assert state.steps == 0
        assert state.baseline is None


class TestCalculatorDBIntegration:
    """Интеграция калькулятора с записями в БД."""

    def test_distance_consistency(self, db_with_activity):
        """Дистанция в БД совпадает с расчётом калькулятора."""
        s, d, _ = db_with_activity.get_activity_for_date('2026-04-01')
        expected = FitnessCalculator.calculate_distance(s, 175.0)
        assert d == expected

    def test_calories_consistency(self, db_with_activity):
        """Калории в БД совпадают с расчётом калькулятора."""
        s, _, k = db_with_activity.get_activity_for_date('2026-04-01')
        expected = FitnessCalculator.calculate_calories(s, 70.0)
        assert k == expected

    def test_all_days_consistent(self, db_with_activity):
        """Все 7 дней имеют согласованные dist/kcal."""
        for i in range(7):
            date_str = (datetime(2026, 4, 1) + timedelta(days=i)).strftime(
                '%Y-%m-%d')
            s, d, k = db_with_activity.get_activity_for_date(date_str)
            assert d == FitnessCalculator.calculate_distance(s, 175.0)
            assert k == FitnessCalculator.calculate_calories(s, 70.0)
