"""
Интеграция с Health Connect (Android).

Полностью асинхронный подход — ВСЕ Java/Kotlin операции
выполняются на ГЛАВНОМ потоке Kivy (где classloader видит DEX).
Результат Kotlin suspend-функций получаем через Continuation + Clock polling.

Предоставляет:
  is_available()            – HC доступен на устройстве
  has_read_permissions()    – разрешения на чтение уже выданы
  HC_READ_PERMISSIONS       – список строк разрешений
  sync_from_hc(db, days, on_done)  – читает HC и пишет в локальную БД
"""

import logging
import os
import threading
from datetime import datetime

logger = logging.getLogger('FitnessTracker.HealthConnect')

ANDROID = False
try:
    from jnius import autoclass, PythonJavaClass, java_method
    ANDROID = True
except ImportError:
    pass

# Разрешения на чтение данных из Health Connect
HC_READ_PERMISSIONS = [
    'android.permission.health.READ_STEPS',
]

# Имена пакетов Health Connect
_HC_PROVIDER_PACKAGES = [
    'com.google.android.apps.healthdata',   # Google Play версия
]


# ── Определение платформы ─────────────────────────────────────────────

def _get_sdk_int():
    """Возвращает API level устройства."""
    try:
        Build = autoclass('android.os.Build$VERSION')
        return Build.SDK_INT
    except Exception:
        return 0


def _check_hc_available(context):
    """Проверяет доступность Health Connect."""
    # Способ 1: проверяем пакет через PackageManager
    try:
        pm = context.getPackageManager()
        for pkg in _HC_PROVIDER_PACKAGES:
            try:
                pm.getPackageInfo(pkg, 0)
                logger.info(f"HC: пакет {pkg} найден через getPackageInfo!")
                return True
            except Exception:
                pass
    except Exception:
        pass

    # Способ 2: через Intent
    try:
        Intent = autoclass('android.content.Intent')
        pm = context.getPackageManager()
        intent = Intent('androidx.health.ACTION_SHOW_PERMISSIONS_RATIONALE')
        if intent.resolveActivity(pm) is not None:
            logger.info("HC: найден через resolveActivity")
            return True
    except Exception:
        pass

    return False


def is_available():
    """Возвращает True, если Health Connect доступен на устройстве."""
    if not ANDROID:
        return False
    try:
        sdk = _get_sdk_int()
        logger.info(f"HC: SDK level = {sdk}")

        if sdk >= 34:
            try:
                autoclass('android.health.connect.HealthConnectManager')
                logger.info("HC: HealthConnectManager (API 34+) доступен")
                return True
            except Exception:
                pass

        if sdk >= 26:
            PythonActivity = autoclass('org.kivy.android.PythonActivity')
            context = PythonActivity.mActivity
            available = _check_hc_available(context)
            logger.info(f"HC: available = {available}")
            return available

        return False
    except Exception as e:
        logger.warning(f"HC availability check failed: {e}")
        return False


def has_read_permissions():
    """Возвращает True, если все разрешения на чтение HC уже выданы."""
    if not ANDROID:
        return False
    try:
        from android.permissions import check_permission
        return all(check_permission(p) for p in HC_READ_PERMISSIONS)
    except Exception as e:
        logger.warning(f"HC permission check failed: {e}")
        return False


# ── Continuation (Java → Python callback) ────────────────────────────

if ANDROID:
    class _KotlinContinuation(PythonJavaClass):
        """kotlin.coroutines.Continuation для вызова suspend-функций.
        ДОЛЖЕН создаваться на MAIN THREAD — pyjnius при создании
        Java-прокси ищет kotlin.coroutines.Continuation через classloader
        текущего потока. Фоновые потоки не видят DEX-классы."""
        __javainterfaces__ = ['kotlin/coroutines/Continuation']
        __javacontext__ = 'app'

        def __init__(self, empty_cc_instance):
            super().__init__()
            self._event = threading.Event()
            self._result = None
            self._error = None
            self._empty_cc = empty_cc_instance

        @java_method('()Lkotlin/coroutines/CoroutineContext;')
        def getContext(self):
            return self._empty_cc

        @java_method('(Ljava/lang/Object;)V')
        def resumeWith(self, result):
            try:
                class_name = result.getClass().getName()
                if 'Failure' in class_name:
                    self._error = str(result.toString())
                else:
                    self._result = result
            except Exception:
                self._result = result
            self._event.set()


# ── Утилиты ──────────────────────────────────────────────────────────

# Файл-флаг для сигнала сервису о том, что HC обновил данные
from database import DB_PATH as _DB_PATH
HC_SYNC_FLAG = os.path.join(_DB_PATH, '.hc_sync')


def _merge_steps_to_db(db, steps_by_day):
    """Объединяет шаги HC с локальной БД.
    Дистанция и калории вычисляются локально через FitnessCalculator."""
    from calculator import FitnessCalculator
    metrics = db.get_latest_metrics()
    weight = float(metrics[0]) if metrics else 70.0
    height = float(metrics[1]) if metrics else 170.0

    today = datetime.now().strftime('%Y-%m-%d')
    today_updated = False

    merged = 0
    for day in sorted(steps_by_day):
        hc_steps = steps_by_day[day]
        if hc_steps <= 0:
            continue
        local_steps, _, _ = db.get_activity_for_date(day)
        if hc_steps > local_steps:
            dist_km = FitnessCalculator.calculate_distance(hc_steps, height)
            kcal = FitnessCalculator.calculate_calories(hc_steps, weight)
            db.update_day_activity(day, hc_steps, dist_km, kcal)
            merged += 1
            if day == today:
                today_updated = True

    # Если обновили сегодняшние шаги — сбрасываем baseline датчика,
    # чтобы сервис пересчитал его с учётом HC-данных
    if today_updated:
        db.delete_sensor_baseline(today)
        try:
            with open(HC_SYNC_FLAG, 'w') as f:
                f.write('1')
        except OSError:
            pass
        logger.info("HC merge: baseline сброшен, флаг записан")

    return merged, len(steps_by_day)


def _is_suspended(result):
    """Проверяет, вернула ли suspend-функция маркер COROUTINE_SUSPENDED."""
    if result is None:
        return False
    try:
        return str(result.toString()) == 'COROUTINE_SUSPENDED'
    except Exception:
        return False


# ── Главная функция синхронизации (main thread, async) ───────────────

def sync_from_hc(db, days=30, on_done=None):
    """
    Читает шаги из Health Connect за последние ``days`` дней.
    Дистанция и калории вычисляются локально через FitnessCalculator.

    ВСЕ Java-вызовы на ГЛАВНОМ потоке (classloader видит DEX).
    Результат suspend-функции получаем через Continuation callback
    + Clock.schedule_interval polling.

    on_done(success: bool, message: str) вызывается в главном потоке.
    """
    if not ANDROID:
        if on_done:
            on_done(False, "Health Connect недоступен (не Android)")
        return

    from kivy.clock import Clock
    import time as _time

    try:
        logger.info("HC sync: загружаем Java-классы на main thread...")

        # ── Загружаем ВСЕ классы на главном потоке ──
        PythonActivity = autoclass('org.kivy.android.PythonActivity')
        HCClient = autoclass(
            'androidx.health.connect.client.HealthConnectClient')
        Instant = autoclass('java.time.Instant')
        TimeRangeFilter = autoclass(
            'androidx.health.connect.client.time.TimeRangeFilter')
        ReadRecordsRequest = autoclass(
            'androidx.health.connect.client.request.ReadRecordsRequest')
        JvmClassMappingKt = autoclass('kotlin.jvm.JvmClassMappingKt')
        Collections = autoclass('java.util.Collections')
        ZoneId = autoclass('java.time.ZoneId')
        EmptyCC = autoclass('kotlin.coroutines.EmptyCoroutineContext')

        # StepsRecord через context classloader (для DEX-классов)
        Thread = autoclass('java.lang.Thread')
        cl = Thread.currentThread().getContextClassLoader()
        steps_java_class = cl.loadClass(
            'androidx.health.connect.client.records.StepsRecord')
        kclass = JvmClassMappingKt.getKotlinClass(steps_java_class)

        logger.info("HC sync: классы загружены, получаем клиент...")

        # ── Получаем клиент ──
        context = PythonActivity.mActivity
        client = HCClient.getOrCreate(context)

        # ── Строим запрос ──
        end_ms = int(_time.time() * 1000)
        start_ms = end_ms - days * 24 * 3600 * 1000

        start_instant = Instant.ofEpochMilli(int(start_ms))
        end_instant = Instant.ofEpochMilli(int(end_ms))
        time_filter = TimeRangeFilter.between(start_instant, end_instant)

        request = ReadRecordsRequest(
            kclass, time_filter, Collections.emptySet(),
            True, 1000, None)

        logger.info("HC sync: запрос построен, создаём Continuation...")

        # ── Создаём Continuation на ГЛАВНОМ потоке ──
        cont = _KotlinContinuation(EmptyCC.INSTANCE)

        logger.info("HC sync: вызываем readRecords...")

        # ── Вызываем readRecords (non-blocking suspend) ──
        result = client.readRecords(request, cont)

        # Если результат пришёл синхронно (не suspended)
        if not _is_suspended(result) and result is not None:
            logger.info("HC sync: результат получен синхронно")
            _process_read_response(result, ZoneId, db, on_done)
            return

        logger.info("HC sync: функция suspended, ждём callback...")

        # ── Ожидаем результат через polling ──
        zone = ZoneId.systemDefault()
        _poll_event = [None]  # ссылка на scheduled event для отмены

        def _check_result(dt):
            if not cont._event.is_set():
                return  # ещё не готово, продолжаем polling

            # Результат получен — отменяем polling
            if _poll_event[0]:
                _poll_event[0].cancel()
                _poll_event[0] = None

            if cont._error:
                logger.error(f"HC readRecords error: {cont._error}")
                if on_done:
                    on_done(False, cont._error)
                return

            try:
                _process_read_response(cont._result, ZoneId, db, on_done)
            except Exception as e:
                logger.error(f"HC process error: {e}", exc_info=True)
                if on_done:
                    on_done(False, str(e))

        _poll_event[0] = Clock.schedule_interval(_check_result, 0.2)

        # Таймаут 30 секунд
        def _timeout(dt):
            if cont._event.is_set():
                return  # уже обработано
            if _poll_event[0]:
                _poll_event[0].cancel()
                _poll_event[0] = None
            logger.error("HC sync: таймаут 30с")
            if on_done:
                on_done(False, "Таймаут ожидания Health Connect (30с)")

        Clock.schedule_once(_timeout, 30)

    except Exception as e:
        logger.error(f"HC sync error: {e}", exc_info=True)
        if on_done:
            on_done(False, str(e))


def _process_read_response(response, ZoneId, db, on_done):
    """Обрабатывает ReadRecordsResponse — извлекает шаги, пишет в БД."""
    records = response.getRecords()
    zone = ZoneId.systemDefault()
    steps_by_day = {}

    for i in range(records.size()):
        r = records.get(i)
        local_date = r.getStartTime().atZone(zone).toLocalDate()
        day = str(local_date.toString())
        steps_by_day[day] = steps_by_day.get(day, 0) + int(r.getCount())

    merged, total = _merge_steps_to_db(db, steps_by_day)
    msg = f"Обновлено {merged} записей из {total} дней Health Connect"
    logger.info(f"HC sync: {msg}")
    if on_done:
        on_done(True, msg)
