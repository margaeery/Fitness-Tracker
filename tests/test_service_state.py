"""Модульные тесты: ServiceState (логика фонового сервиса)."""

import pytest
import os
from datetime import datetime
from unittest.mock import patch, MagicMock


class TestServiceState:
    """Тесты ServiceState без Android-зависимостей.
    
    ServiceState — чистая Python-логика (не зависит от Android),
    поэтому можно тестировать импортируя напрямую.
    """

    @pytest.fixture
    def state(self, db_with_metrics):
        """Создаёт ServiceState с test БД."""
        # Подменяем android-зависимые глобальные переменные service.py
        import service as svc
        svc.FOREGROUND_FLAG = os.path.join(
            os.path.dirname(db_with_metrics.conn.execute(
                "PRAGMA database_list").fetchone()[2]),
            '.app_foreground_test')
        svc.HC_SYNC_FLAG = os.path.join(
            os.path.dirname(db_with_metrics.conn.execute(
                "PRAGMA database_list").fetchone()[2]),
            '.hc_sync_test')

        return svc.ServiceState(db_with_metrics)

    def test_initial_load(self, state):
        """Начальное состояние корректно загружается из БД."""
        assert state.weight == 70.0
        assert state.height == 175.0
        assert state.goal == 10000
        assert state.steps == 0
        assert state.baseline is None
        assert state.dirty is False

    def test_first_sensor_reading_sets_baseline(self, state):
        """Первое чтение датчика устанавливает baseline."""
        changed = state.process_sensor(50000)
        assert changed is False  # baseline только установлен
        assert state.baseline == 50000  # sensor - 0 steps

    def test_subsequent_readings_count_steps(self, state):
        """Последующие чтения увеличивают счётчик шагов."""
        state.process_sensor(50000)  # baseline
        changed = state.process_sensor(50100)  # +100 шагов
        assert changed is True
        assert state.steps == 100

    def test_no_change_returns_false(self, state):
        """Если шаги не изменились — False."""
        state.process_sensor(50000)
        state.process_sensor(50100)
        changed = state.process_sensor(50100)  # без изменений
        assert changed is False

    def test_reboot_detection(self, state):
        """Обнаружение перезагрузки (датчик < baseline)."""
        state.process_sensor(50000)  # baseline = 50000
        state.process_sensor(50200)  # steps = 200

        # Имитируем перезагрузку: sensor сбросился
        state.process_sensor(100)  # sensor < baseline
        # baseline пересчитан: 100 - 200 = -100
        assert state.baseline == 100 - 200  # сохраняет набранные шаги

    @patch('service.send_goal_notification')
    def test_goal_notification(self, mock_notify, state, db_with_metrics):
        """Уведомление отправляется при достижении цели."""
        # Цель = 10000, установим маленькую
        db_with_metrics.save_user_metrics(70.0, 175.0, 100)
        state.goal = 100

        state.process_sensor(50000)  # baseline
        state.process_sensor(50150)  # 150 шагов >= 100 цели

        mock_notify.assert_called_once()

    @patch('service.send_goal_notification')
    def test_goal_notified_only_once(self, mock_notify, state, db_with_metrics):
        """Уведомление о цели отправляется только один раз в день."""
        db_with_metrics.save_user_metrics(70.0, 175.0, 100)
        state.goal = 100

        state.process_sensor(50000)
        state.process_sensor(50150)  # 150 >= 100 → уведомление
        state.process_sensor(50200)  # ещё шаги → повторного уведомления нет

        assert mock_notify.call_count == 1

    def test_save_to_db(self, state):
        """save_to_db записывает данные в БД."""
        state.process_sensor(50000)
        state.process_sensor(50500)  # 500 шагов
        state.save_to_db()

        steps, dist, kcal = state.db.get_activity_for_date(state.current_date)
        assert steps == 500
        assert dist > 0
        assert kcal > 0

    def test_save_not_dirty(self, state):
        """save_to_db без dirty не пишет в БД."""
        state.dirty = False
        state.save_to_db()
        # Нет данных
        steps, _, _ = state.db.get_activity_for_date(state.current_date)
        assert steps == 0

    def test_save_protects_hc_data(self, state):
        """Если в БД больше шагов (от HC), сервис не перезаписывает."""
        state.db.update_day_activity(state.current_date, 10000, 7.0, 400.0)

        state.process_sensor(50000)  # baseline
        state.process_sensor(50100)  # 100 шагов (меньше чем 10000 в БД)
        state.save_to_db()

        steps, _, _ = state.db.get_activity_for_date(state.current_date)
        assert steps == 10000  # HC данные сохранены

    def test_handle_midnight(self, state):
        """Смена дня сбрасывает состояние."""
        state.process_sensor(50000)
        state.process_sensor(50500)  # 500 шагов

        # Имитируем смену дня
        state.current_date = '2026-04-01'
        with patch('service.datetime') as mock_dt:
            mock_dt.now.return_value = datetime(2026, 4, 2, 0, 0, 1)
            mock_dt.side_effect = lambda *a, **k: datetime(*a, **k)
            state.handle_midnight()

        assert state.current_date == '2026-04-02'
        assert state.baseline is None
        assert state.steps == 0

    def test_check_hc_sync(self, state, tmp_path):
        """check_hc_sync перечитывает БД при наличии флаг-файла."""
        import service as svc
        flag = svc.HC_SYNC_FLAG

        # Записываем шаги от HC напрямую в БД
        state.db.update_day_activity(state.current_date, 9000, 6.0, 350.0)

        # Создаём флаг
        os.makedirs(os.path.dirname(flag), exist_ok=True)
        with open(flag, 'w') as f:
            f.write('1')

        state.check_hc_sync()
        assert state.steps == 9000
        assert not os.path.exists(flag)  # флаг удалён

    def test_check_goal_change(self, state, db_with_metrics):
        """check_goal_change обновляет цель из БД."""
        assert state.goal == 10000
        db_with_metrics.save_user_metrics(70.0, 175.0, 15000)
        state.check_goal_change()
        assert state.goal == 15000
