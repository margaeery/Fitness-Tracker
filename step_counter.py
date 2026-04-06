"""
Модуль подсчёта шагов через аппаратный датчик Android (TYPE_STEP_COUNTER).

TYPE_STEP_COUNTER — аппаратный датчик, возвращающий суммарное число шагов
с момента последней перезагрузки устройства. Для вычисления дневных шагов
хранится baseline (начальное значение датчика на начало дня):

    шаги_за_день = текущее_значение_датчика − baseline

Обработка особых случаев:
 • Первый запуск за день — baseline устанавливается с учётом уже
   накопленных шагов (если были добавлены вручную).
 • Перезагрузка устройства — датчик сбрасывается в 0, baseline
   пересчитывается так, чтобы сохранить уже набранные шаги.
 • Смена дня (полночь) — baseline сбрасывается.

На десктопе (не Android) модуль работает в режиме заглушки: датчик
не регистрируется, подсчёт шагов не ведётся.
"""

import logging
from datetime import datetime
from kivy.clock import Clock
from calculator import FitnessCalculator

logger = logging.getLogger('FitnessTracker.StepCounter')

# Проверка платформы
ANDROID = False
try:
    from jnius import autoclass, PythonJavaClass, java_method
    PythonActivity = autoclass('org.kivy.android.PythonActivity')
    Context = autoclass('android.content.Context')
    Sensor = autoclass('android.hardware.Sensor')
    SensorManager = autoclass('android.hardware.SensorManager')
    ANDROID = True
    logger.info("Платформа Android — датчики доступны")
except ImportError:
    logger.info("Платформа Desktop — датчики недоступны")


# Java-обёртка SensorEventListener
if ANDROID:
    class _SensorListener(PythonJavaClass):
        """Реализация android.hardware.SensorEventListener через pyjnius."""
        __javainterfaces__ = ['android/hardware/SensorEventListener']
        __javacontext__ = 'app'

        def __init__(self, callback):
            super().__init__()
            self._callback = callback

        @java_method('(Landroid/hardware/SensorEvent;)V')
        def onSensorChanged(self, event):
            try:
                self._callback(int(event.values[0]))
            except Exception as e:
                logger.error(f"onSensorChanged error: {e}")

        @java_method('(Landroid/hardware/Sensor;I)V')
        def onAccuracyChanged(self, sensor, accuracy):
            logger.debug(f"Точность датчика изменилась: {accuracy}")


# Основной класс
class StepCounter:
    """Подсчёт шагов через аппаратный датчик TYPE_STEP_COUNTER."""

    def __init__(self, db):
        self.db = db
        self.is_running = False
        self._listener = None
        self._sensor_manager = None
        self._step_sensor = None
        self._current_date = datetime.now().strftime('%Y-%m-%d')
        self._ui_callback = None
        self._goal_reached_today = False
        logger.info("StepCounter создан")

    # Публичные методы

    def start(self, ui_callback=None):
        """
        Запуск прослушивания датчика шагов.

        Параметры:
            ui_callback(steps: int) — вызывается при каждом обновлении
                                      числа шагов.
        Возвращает True при успешной регистрации датчика.
        """
        self._ui_callback = ui_callback

        if not ANDROID:
            logger.warning("Датчик шагов недоступен (не Android)")
            return False

        try:
            activity = PythonActivity.mActivity
            self._sensor_manager = activity.getSystemService(
                Context.SENSOR_SERVICE
            )
            self._step_sensor = self._sensor_manager.getDefaultSensor(
                Sensor.TYPE_STEP_COUNTER
            )

            if self._step_sensor is None:
                logger.error(
                    "TYPE_STEP_COUNTER отсутствует на этом устройстве"
                )
                return False

            self._listener = _SensorListener(self._on_sensor_event)
            registered = self._sensor_manager.registerListener(
                self._listener,
                self._step_sensor,
                SensorManager.SENSOR_DELAY_UI,
            )

            if registered:
                self.is_running = True
                logger.info("Датчик шагов зарегистрирован")
            else:
                logger.error("Не удалось зарегистрировать датчик")

            return registered

        except Exception as e:
            logger.error(f"Ошибка запуска датчика: {e}", exc_info=True)
            return False

    def stop(self):
        """Отключает прослушивание датчика шагов."""
        if self._sensor_manager and self._listener:
            try:
                self._sensor_manager.unregisterListener(self._listener)
                logger.info("Датчик шагов остановлен")
            except Exception as e:
                logger.error(f"Ошибка остановки датчика: {e}")
        self.is_running = False

    # Внутренняя логика

    def _on_sensor_event(self, sensor_value):
        """Вызывается из Java-потока — безопасно переключаемся в Kivy."""
        Clock.schedule_once(lambda dt: self._process_step(sensor_value), 0)

    def _process_step(self, sensor_value):
        """Обработка нового значения датчика (главный поток Kivy)."""
        today = datetime.now().strftime('%Y-%m-%d')

        # Проверяем смену дня (полночь)
        if today != self._current_date:
            logger.info(f"Смена дня: {self._current_date} → {today}")
            self._current_date = today
            self._goal_reached_today = False

        baseline = self.db.get_sensor_baseline(today)
        current_steps = self.db.get_today_steps()

        # Первое чтение за день
        if baseline is None:
            # baseline = sensor − уже накопленные шаги (из ручного ввода и т.д.)
            new_baseline = sensor_value - current_steps
            self.db.save_sensor_baseline(today, new_baseline)
            logger.info(
                f"Baseline установлен: date={today}, sensor={sensor_value}, "
                f"existing_steps={current_steps}, baseline={new_baseline}"
            )
            return

        #  Перезагрузка устройства (датчик сбросился)
        if sensor_value < baseline:
            new_baseline = sensor_value - current_steps
            self.db.save_sensor_baseline(today, new_baseline)
            logger.warning(
                f"Сброс датчика (reboot): sensor={sensor_value}, "
                f"old_baseline={baseline}, preserved_steps={current_steps}, "
                f"new_baseline={new_baseline}"
            )
            return

        # Обычная работа: вычисляем шаги
        new_steps = sensor_value - baseline

        if new_steps == current_steps:
            return  # нет изменений

        # Получаем параметры пользователя для расчёта дистанции и калорий
        metrics = self.db.get_latest_metrics()
        if not metrics:
            logger.warning("Параметры пользователя не заданы — "
                           "дистанция/калории не обновлены")
            return

        weight, height, goal = metrics
        dist = FitnessCalculator.calculate_distance(new_steps, height)
        kcal = FitnessCalculator.calculate_calories(new_steps, weight)
        self.db.update_day_activity(today, new_steps, dist, kcal)

        logger.debug(
            f"Шаги: {new_steps} | Дистанция: {dist} км | "
            f"Калории: {kcal} ккал  (sensor={sensor_value}, baseline={baseline})"
        )

        # Проверяем достижение цели
        if not self._goal_reached_today and new_steps >= goal > 0:
            self._goal_reached_today = True
            logger.info(f"Цель достигнута! {new_steps}/{goal} шагов")
            self._send_goal_notification(new_steps, goal)

        # Обновляем UI
        if self._ui_callback:
            self._ui_callback(new_steps)

    # Push-уведомление о достижении цели

    def _send_goal_notification(self, steps, goal):
        """Отправляет Android-уведомление при достижении цели шагов."""
        if not ANDROID:
            return
        try:
            NB = autoclass('android.app.Notification$Builder')
            NM_cls = autoclass('android.app.NotificationManager')

            activity = PythonActivity.mActivity
            context = activity.getApplicationContext()
            nm = context.getSystemService(Context.NOTIFICATION_SERVICE)

            channel_id = "fitness_goals"

            # NotificationChannel обязателен для API 26+
            try:
                NC = autoclass('android.app.NotificationChannel')
                channel = NC(
                    channel_id, "Цели", NM_cls.IMPORTANCE_DEFAULT
                )
                nm.createNotificationChannel(channel)
            except Exception:
                # API < 26 — канал не нужен
                channel_id = None

            builder = (
                NB(context, channel_id) if channel_id else NB(context)
            )
            builder.setContentTitle("Цель достигнута!")
            builder.setContentText(
                f"Вы прошли {steps} из {goal} шагов!"
            )
            # Используем иконку приложения
            builder.setSmallIcon(context.getApplicationInfo().icon)
            builder.setAutoCancel(True)

            nm.notify(1001, builder.build())
            logger.info("Push-уведомление отправлено")

        except Exception as e:
            logger.error(f"Ошибка уведомления: {e}", exc_info=True)
