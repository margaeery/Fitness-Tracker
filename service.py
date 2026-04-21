"""
Фоновый сервис для подсчёта шагов (Android).

Работает в отдельном процессе, независимо от UI.
- Регистрирует аппаратный датчик TYPE_STEP_COUNTER через HandlerThread
- В фоне (приложение свёрнуто/закрыто): проверяет датчик каждые 60 сек,
  пишет в БД каждые 10 мин — экономия батареи
- Когда приложение на экране (foreground): проверяет датчик каждые 15 сек,
  пишет в БД каждые 15 сек — быстрое обновление UI
- Обрабатывает смену дня (полночь): сохраняет данные за прошлый день,
  сбрасывает baseline для нового
- Отправляет push-уведомление через plyer при достижении цели шагов
- setAutoRestartService(True) — Android перезапускает сервис при убийстве

Коммуникация с приложением:
  Приложение создаёт/удаляет файл-флаг «.app_foreground» — сервис
  читает его и переключает режим (foreground/background).
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

from database import FitnessDB, DB_PATH
from calculator import FitnessCalculator

# Файл-флаг: приложение на экране
FOREGROUND_FLAG = os.path.join(DB_PATH, '.app_foreground')
# Файл-флаг: HC обновил данные, нужно перечитать БД
HC_SYNC_FLAG = os.path.join(DB_PATH, '.hc_sync')

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
    PowerManager  = autoclass('android.os.PowerManager')
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

        # Проверяем достижение цели (через БД — одно уведомление в день)
        if self.goal > 0 and self.steps >= self.goal:
            if not self.db.get_goal_achieved(self.current_date):
                self.db.set_goal_achieved(self.current_date)
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

        # Защита от перезаписи HC-данных: если в БД больше шагов,
        # принимаем значение из БД и пересчитываем baseline
        db_steps = self.db.get_today_steps()
        if db_steps > self.steps:
            logger.info(
                f"DB содержит больше шагов ({db_steps} > {self.steps}), "
                f"принимаем HC-значение"
            )
            self.steps = db_steps
            self.baseline = None  # пересчитается при следующем чтении датчика
            self.db.delete_sensor_baseline(self.current_date)
            self.dirty = False
            self.last_save_time = time.time()
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
        self.dirty = False
        self.last_save_time = time.time()

        # Перечитываем метрики (могли измениться)
        metrics = self.db.get_latest_metrics()
        if metrics:
            self.weight, self.height, self.goal = metrics

    def check_hc_sync(self):
        """Проверяет, обновил ли HC данные. Если да — перечитывает БД."""
        if not os.path.exists(HC_SYNC_FLAG):
            return
        try:
            os.remove(HC_SYNC_FLAG)
        except OSError:
            pass
        old_steps = self.steps
        self.dirty = False  # предотвращаем перезапись старыми данными
        self._load_from_db()
        logger.info(
            f"HC sync detected: steps {old_steps} → {self.steps}, "
            f"baseline={self.baseline}"
        )

    def check_goal_change(self):
        """Проверяет, изменилась ли цель. Если да — сбрасывает флаг уведомления."""
        metrics = self.db.get_latest_metrics()
        if not metrics:
            return
        new_goal = metrics[2]
        if new_goal != self.goal:
            old_goal = self.goal
            self.weight, self.height, self.goal = metrics
            # Сбрасываем флаг уведомления в БД
            self.db.reset_goal_achieved(self.current_date)
            logger.info(f"Цель изменена: {old_goal} → {self.goal}, "
                        f"флаг сброшен")


# Точка входа сервиса  
def main():
    logger.info("═══ StepService запускается ═══")

    service = PythonService.mService
    # НЕ вызываем setAutoRestartService до startForeground:
    # На API 34+ без foregroundServiceType startForeground падает,
    # и auto-restart вызвал бы бесконечный цикл перезапусков.

    # Меняем текст постоянного уведомления сервиса
    fg_ok = False
    try:
        NotificationBuilder = autoclass('android.app.Notification$Builder')
        NotificationManager = autoclass('android.app.NotificationManager')
        NotificationChannel = autoclass('android.app.NotificationChannel')

        context = service.getApplicationContext()
        nm = context.getSystemService(Context.NOTIFICATION_SERVICE)

        channel_id = "fitness_service"
        channel = NotificationChannel(
            channel_id, "Фоновый сервис",
            NotificationManager.IMPORTANCE_LOW,
        )
        channel.setDescription("Подсчёт шагов в фоновом режиме")
        nm.createNotificationChannel(channel)

        builder = NotificationBuilder(context, channel_id)
        builder.setContentTitle("FitnessTracker")
        builder.setContentText("Работа в фоновом режиме")
        builder.setSmallIcon(context.getApplicationInfo().icon)
        builder.setOngoing(True)

        notification = builder.build()

        # API 34+ требует foregroundServiceType
        sdk = autoclass('android.os.Build$VERSION').SDK_INT
        if sdk >= 34:
            ServiceInfo = autoclass('android.content.pm.ServiceInfo')
            service.startForeground(
                1, notification,
                ServiceInfo.FOREGROUND_SERVICE_TYPE_HEALTH)
        else:
            service.startForeground(1, notification)

        fg_ok = True
        logger.info(f"Foreground сервис запущен (SDK {sdk})")
    except Exception as e:
        logger.warning(f"Не удалось запустить foreground сервис: {e}")

    # Включаем auto-restart только после успешного startForeground
    if fg_ok:
        service.setAutoRestartService(True)

    # WakeLock — не даём CPU засыпать, иначе датчик не читается
    pm = service.getSystemService(Context.POWER_SERVICE)
    wake_lock = pm.newWakeLock(
        PowerManager.PARTIAL_WAKE_LOCK, 'FitnessTracker::StepService'
    )
    wake_lock.acquire()

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

    # Интервалы для двух режимов
    # Background (приложение свёрнуто/закрыто): экономим батарею
    BG_CHECK  = 60    # проверка датчика каждые 60 сек
    BG_SAVE   = 600   # запись в БД каждые 10 мин

    # Foreground (приложение на экране): быстрое обновление
    FG_CHECK  = 10    # проверка датчика каждые 10 сек
    FG_SAVE   = 15    # запись в БД каждые 15 сек (совпадает с check)

    # HC sync из сервиса (в фоне ~10 мин)
    HC_BG_INTERVAL = 600  # 10 мин

    current_mode = 'background'
    check_interval = BG_CHECK
    save_interval  = BG_SAVE
    last_hc_sync = 0  # момент последнего HC sync из сервиса

    logger.info(f"Начальный режим: {current_mode} "
                f"(check={check_interval}s, save={save_interval}s)")

    try:
        while True:
            # Проверяем режим (foreground / background)
            app_active = os.path.exists(FOREGROUND_FLAG)
            new_mode = 'foreground' if app_active else 'background'

            if new_mode != current_mode:
                # При смене режима — сразу сохраняем актуальные данные
                state.dirty = True
                state.save_to_db()
                current_mode = new_mode
                if current_mode == 'foreground':
                    check_interval, save_interval = FG_CHECK, FG_SAVE
                else:
                    check_interval, save_interval = BG_CHECK, BG_SAVE
                logger.info(f"Режим → {current_mode} "
                            f"(check={check_interval}s, save={save_interval}s)")

            # Проверяем, обновил ли HC данные
            state.check_hc_sync()

            # Проверяем смену дня
            state.handle_midnight()

            # Проверяем изменение цели 
            state.check_goal_change()

            # Обрабатываем данные датчика 
            if listener.last_sensor_value is not None:
                state.process_sensor(listener.last_sensor_value)

            #  Периодическая запись в БД  
            if time.time() - state.last_save_time >= save_interval:
                state.save_to_db()

            # HC sync из сервиса (только в фоне, ~10 мин)
            # В foreground HC sync делает основное приложение каждые 20с
            if current_mode == 'background' and \
               time.time() - last_hc_sync >= HC_BG_INTERVAL:
                try:
                    import health_connect as hc_mod
                    svc_context = PythonService.mService
                    success, msg = hc_mod.sync_from_hc_blocking(
                        db, svc_context, days=1)
                    logger.info(f"HC bg-sync: {success}, {msg}")
                    if success:
                        state.check_hc_sync()
                except Exception as e:
                    logger.debug(f"HC bg-sync: {e}")
                last_hc_sync = time.time()

            #  Ждём до следующей проверки  
            time.sleep(check_interval)

    except Exception as e:
        logger.error(f"Ошибка сервиса: {e}", exc_info=True)
    finally:
        logger.info("═══ StepService останавливается ═══")
        state.dirty = True
        state.save_to_db()
        sm.unregisterListener(listener)
        if wake_lock.isHeld():
            wake_lock.release()
        ht.quit()
        db.close()


if __name__ == '__main__':
    main()
