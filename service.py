"""
Фоновый сервис для подсчёта шагов (Android).

Работает в отдельном процессе, независимо от UI.
- Регистрирует аппаратный датчик TYPE_STEP_COUNTER через HandlerThread
- Каждые 30 секунд проверяет новые данные датчика
- Сохраняет данные в SQLite каждые 2 минуты (или при достижении цели)
- Обрабатывает смену дня (полночь): сохраняет данные за прошлый день,
  сбрасывает baseline для нового
- Отправляет push-уведомление через plyer при достижении цели шагов
"""

import os
import sys
import time
import logging
from datetime import datetime

# Путь к исходникам (для импорта database, calculator)
SERVICE_DIR = os.path.dirname(os.path.abspath(__file__))
if SERVICE_DIR not in sys.path:
    sys.path.insert(0, SERVICE_DIR)

from database import FitnessDB
from calculator import FitnessCalculator

# Логирование
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s [%(name)s] %(levelname)s: %(message)s',
    datefmt='%H:%M:%S',
)
logger = logging.getLogger('FitnessTracker.Service')

# Android-импорты
try:
    from jnius import autoclass, PythonJavaClass, java_method

    PythonService = autoclass('org.kivy.android.PythonService')
    Context       = autoclass('android.content.Context')
    Sensor        = autoclass('android.hardware.Sensor')
    SensorManager = autoclass('android.hardware.SensorManager')
    HandlerThread = autoclass('android.os.HandlerThread')
    Handler       = autoclass('android.os.Handler')
except ImportError:
    logger.error("Service запущен не на Android — выход")
    sys.exit(1)


# SensorEventListener  
class StepSensorListener(PythonJavaClass):
    """Слушатель датчика шагов. Работает в потоке HandlerThread."""
    __javainterfaces__ = ['android/hardware/SensorEventListener']
    __javacontext__ = 'app'

    def __init__(self):
        super().__init__()
        self.last_sensor_value = None

    @java_method('(Landroid/hardware/SensorEvent;)V')
    def onSensorChanged(self, event):
        try:
            self.last_sensor_value = int(event.values[0])
        except Exception as e:
            logger.error(f"onSensorChanged error: {e}")

    @java_method('(Landroid/hardware/Sensor;I)V')
    def onAccuracyChanged(self, sensor, accuracy):
        pass


# Push-уведомление о достижении цели  
def send_goal_notification():
    """Отправляет уведомление при достижении цели.
    Пробует plyer, при неудаче — через Java Notification API."""
    try:
        # Подменяем контекст: plyer ожидает mActivity, а в сервисе его нет
        import android
        if not hasattr(android, 'mActivity') or android.mActivity is None:
            android.mActivity = PythonService.mService

        from plyer import notification
        notification.notify(
            title='Цель достигнута!',
            message='Поздравляем! Вы выполнили дневную цель по шагам!',
            app_name='FitnessTracker',
            timeout=10,
        )
        logger.info("Push-уведомление отправлено (plyer)")
    except Exception as e:
        logger.warning(f"plyer не сработал: {e}, пробуем Java API")
        _send_notification_java()


def _send_notification_java():
    """Запасной способ: уведомление через Java Notification API."""
    try:
        context = PythonService.mService.getApplicationContext()

        NotificationBuilder = autoclass('android.app.Notification$Builder')
        NotificationManager = autoclass('android.app.NotificationManager')
        NotificationChannel = autoclass('android.app.NotificationChannel')

        nm = context.getSystemService(Context.NOTIFICATION_SERVICE)

        channel_id = "fitness_goals"
        channel = NotificationChannel(
            channel_id, "Достижение целей",
            NotificationManager.IMPORTANCE_HIGH,
        )
        nm.createNotificationChannel(channel)

        builder = NotificationBuilder(context, channel_id)
        builder.setContentTitle("Цель достигнута!")
        builder.setContentText(
            "Поздравляем! Вы выполнили дневную цель по шагам!"
        )
        builder.setSmallIcon(context.getApplicationInfo().icon)
        builder.setAutoCancel(True)

        nm.notify(1001, builder.build())
        logger.info("Push-уведомление отправлено (Java API)")
    except Exception as e:
        logger.error(f"Java notification failed: {e}", exc_info=True)


# Состояние сервиса (кэш, минимизация обращений к БД)
class ServiceState:
    """Хранит текущее состояние подсчёта шагов в памяти.
    Записывает в БД только периодически."""

    def __init__(self, db):
        self.db = db
        self.current_date = datetime.now().strftime('%Y-%m-%d')
        self.baseline = None
        self.steps = 0
        self.goal_notified = False
        self.weight = 0.0
        self.height = 0.0
        self.goal = 0
        self.last_save_time = time.time()
        self.dirty = False
        self._load_from_db()

    def _load_from_db(self):
        """Загружает начальное состояние из БД."""
        self.baseline = self.db.get_sensor_baseline(self.current_date)
        self.steps = self.db.get_today_steps()
        metrics = self.db.get_latest_metrics()
        if metrics:
            self.weight, self.height, self.goal = metrics
        logger.info(
            f"State loaded: date={self.current_date}, baseline={self.baseline}, "
            f"steps={self.steps}, goal={self.goal}"
        )

    def process_sensor(self, sensor_value):
        """Обрабатывает значение датчика. Возвращает True, если шаги изменились."""

        # Первое чтение за день — устанавливаем baseline
        if self.baseline is None:
            self.baseline = sensor_value - self.steps
            self.db.save_sensor_baseline(self.current_date, self.baseline)
            logger.info(
                f"Baseline установлен: sensor={sensor_value}, "
                f"steps={self.steps}, baseline={self.baseline}"
            )
            return False

        # Перезагрузка устройства — датчик сбросился
        if sensor_value < self.baseline:
            self.baseline = sensor_value - self.steps
            self.db.save_sensor_baseline(self.current_date, self.baseline)
            logger.warning(
                f"Сброс датчика (reboot): sensor={sensor_value}, "
                f"baseline={self.baseline}"
            )
            return False

        new_steps = sensor_value - self.baseline
        if new_steps == self.steps:
            return False

        self.steps = new_steps
        self.dirty = True

        # Проверяем достижение цели
        if not self.goal_notified and self.goal > 0 and self.steps >= self.goal:
            self.goal_notified = True
            logger.info(f"Цель достигнута! {self.steps}/{self.goal}")
            send_goal_notification()
            # Принудительно сохраняем при достижении цели
            self.save_to_db()

        return True

    def save_to_db(self):
        """Сохраняет текущие данные активности в БД."""
        if not self.dirty:
            return
        if self.height <= 0 or self.weight <= 0:
            return

        dist = FitnessCalculator.calculate_distance(self.steps, self.height)
        kcal = FitnessCalculator.calculate_calories(self.steps, self.weight)
        self.db.update_day_activity(self.current_date, self.steps, dist, kcal)
        self.dirty = False
        self.last_save_time = time.time()
        logger.debug(
            f"DB save: date={self.current_date}, steps={self.steps}, "
            f"dist={dist}, kcal={kcal}"
        )

    def handle_midnight(self):
        """Обрабатывает смену дня (полночь)."""
        today = datetime.now().strftime('%Y-%m-%d')
        if today == self.current_date:
            return

        logger.info(f"Смена дня: {self.current_date} → {today}")

        # Финальное сохранение за прошлый день
        self.dirty = True  # форсируем запись
        self.save_to_db()

        # Сброс для нового дня
        self.current_date = today
        self.baseline = None
        self.steps = 0
        self.goal_notified = False
        self.dirty = False
        self.last_save_time = time.time()

        # Перечитываем метрики (могли измениться)
        metrics = self.db.get_latest_metrics()
        if metrics:
            self.weight, self.height, self.goal = metrics


# Точка входа сервиса  
def main():
    logger.info("═══ StepService запускается ═══")

    # Предотвращаем убийство сервиса Android
    service = PythonService.mService
    service.setAutoRestartService(True)

    # База данных
    db = FitnessDB()
    state = ServiceState(db)

    # Регистрация датчика через HandlerThread
    ht = HandlerThread('StepSensorThread')
    ht.start()
    handler = Handler(ht.getLooper())

    context = service.getApplicationContext()
    sm = context.getSystemService(Context.SENSOR_SERVICE)
    step_sensor = sm.getDefaultSensor(Sensor.TYPE_STEP_COUNTER)

    if step_sensor is None:
        logger.error("TYPE_STEP_COUNTER недоступен на устройстве")
        db.close()
        return

    listener = StepSensorListener()
    registered = sm.registerListener(
        listener, step_sensor,
        SensorManager.SENSOR_DELAY_NORMAL, handler,
    )

    if not registered:
        logger.error("Не удалось зарегистрировать датчик в сервисе")
        ht.quit()
        db.close()
        return

    logger.info("Датчик шагов зарегистрирован в сервисе")

    # Основной цикл
    SAVE_INTERVAL  = 120   # Запись в БД каждые 2 минуты
    CHECK_INTERVAL = 30    # Проверка датчика каждые 30 секунд

    try:
        while True:
            time.sleep(CHECK_INTERVAL)

            # Проверяем смену дня
            state.handle_midnight()

            # Обрабатываем данные датчика
            if listener.last_sensor_value is not None:
                state.process_sensor(listener.last_sensor_value)

            # Периодическая запись в БД
            if time.time() - state.last_save_time >= SAVE_INTERVAL:
                state.save_to_db()

    except Exception as e:
        logger.error(f"Ошибка сервиса: {e}", exc_info=True)
    finally:
        logger.info("═══ StepService останавливается ═══")
        state.dirty = True
        state.save_to_db()
        sm.unregisterListener(listener)
        ht.quit()
        db.close()


if __name__ == '__main__':
    main()
