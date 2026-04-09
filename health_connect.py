"""
Интеграция с Health Connect (Android).

Два бэкенда:
  • Android 14+ (API 34): HealthConnectManager — встроен в ОС
  • Android 9–13 (API 28–33): AndroidX HealthConnectClient —
    работает через приложение Health Connect из Google Play.
    Suspend-функции Kotlin вызываются через pyjnius Continuation.

На десктопе и Android < 9 интеграция недоступна.

Предоставляет:
  is_available()            – HC доступен на устройстве
  has_read_permissions()    – разрешения на чтение уже выданы
  HC_READ_PERMISSIONS       – список строк разрешений
  sync_from_hc(db, days, on_done)  – читает HC и пишет в локальную БД
"""

import logging
import threading

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
    'android.permission.health.READ_DISTANCE',
    'android.permission.health.READ_TOTAL_CALORIES_BURNED',
]

# Имена пакетов Health Connect
_HC_PROVIDER_PACKAGES = [
    'com.google.android.apps.healthdata',   # Google Play версия
]

# SDK status константы (из HealthConnectClient)
SDK_UNAVAILABLE = 1
SDK_UNAVAILABLE_PROVIDER_UPDATE_REQUIRED = 2
SDK_AVAILABLE = 3


# ── Определение платформы ─────────────────────────────────────────────

def _get_sdk_int():
    """Возвращает API level устройства."""
    try:
        Build = autoclass('android.os.Build$VERSION')
        return Build.SDK_INT
    except Exception:
        return 0


def _check_hc_available(context):
    """Проверяет доступность Health Connect.
    Для connect-client:1.0.0-alpha11.
    Возвращает True если HC доступен."""

    # Способ 1 (самый надёжный): проверяем пакет через PackageManager
    # Требует <queries> в AndroidManifest — добавлен в шаблон
    try:
        pm = context.getPackageManager()
        for pkg in _HC_PROVIDER_PACKAGES:
            try:
                pm.getPackageInfo(pkg, 0)
                logger.info(f"HC: пакет {pkg} найден через getPackageInfo!")
                return True
            except Exception:
                logger.debug(f"HC: пакет {pkg} не найден через getPackageInfo")
    except Exception as e:
        logger.debug(f"HC: PackageManager check failed: {e}")

    # Способ 2: через Intent (resolveActivity) — тоже зависит от <queries>
    try:
        Intent = autoclass('android.content.Intent')
        pm = context.getPackageManager()
        intent = Intent('androidx.health.ACTION_SHOW_PERMISSIONS_RATIONALE')
        info = intent.resolveActivity(pm)
        if info is not None:
            logger.info("HC: найден через resolveActivity")
            return True
        else:
            logger.debug("HC: resolveActivity вернул null")
    except Exception as e:
        logger.debug(f"HC: intent check failed: {e}")

    # Способ 3: через AndroidX SDK — isAvailable / getSdkStatus
    try:
        HCClient = autoclass('androidx.health.connect.client.HealthConnectClient')
        logger.debug("HC: autoclass HealthConnectClient — OK")

        # Пробуем все варианты вызова
        for method_name in ['isAvailable', 'isProviderAvailable']:
            # С именем пакета
            for pkg in _HC_PROVIDER_PACKAGES:
                try:
                    result = getattr(HCClient, method_name)(context, pkg)
                    logger.info(f"HC: {method_name}(ctx, '{pkg}') = {result}")
                    if result:
                        return True
                except Exception as e:
                    logger.debug(f"HC: {method_name}(ctx, '{pkg}') failed: {e}")
            # Без пакета
            try:
                result = getattr(HCClient, method_name)(context)
                logger.info(f"HC: {method_name}(ctx) = {result}")
                if result:
                    return True
            except Exception as e:
                logger.debug(f"HC: {method_name}(ctx) failed: {e}")

        # getSdkStatus (если доступен в этой версии библиотеки)
        try:
            status = HCClient.getSdkStatus(context)
            logger.info(f"HC: getSdkStatus(ctx) = {status}")
            if status >= SDK_UNAVAILABLE_PROVIDER_UPDATE_REQUIRED:
                # status 2 = установлен но нужно обновить, 3 = доступен
                # Оба случая означают что HC НА УСТРОЙСТВЕ ЕСТЬ
                return True
        except Exception as e:
            logger.debug(f"HC: getSdkStatus failed: {e}")

    except Exception as e:
        logger.debug(f"HC: autoclass HealthConnectClient failed: {e}")

    logger.warning("HC: все способы обнаружения не сработали")
    return False


def _is_hc_app_installed():
    """Проверяет, доступен ли Health Connect (для API < 34)."""
    try:
        PythonActivity = autoclass('org.kivy.android.PythonActivity')
        context = PythonActivity.mActivity
        return _check_hc_available(context)
    except Exception as e:
        logger.error(f"_is_hc_app_installed error: {e}")
        return False


def _get_sdk_status():
    """Возвращает статус HC. Для совместимости с разными версиями библиотеки."""
    if not ANDROID:
        return SDK_UNAVAILABLE
    try:
        PythonActivity = autoclass('org.kivy.android.PythonActivity')
        context = PythonActivity.mActivity
        if _check_hc_available(context):
            return SDK_AVAILABLE
        return SDK_UNAVAILABLE
    except Exception as e:
        logger.debug(f"_get_sdk_status error: {e}")
        return SDK_UNAVAILABLE


def needs_update():
    """Возвращает True, если HC установлен, но требует обновления."""
    return False  # С alpha11 нет способа отличить "нужно обновить" от "нет HC"


def is_available():
    """Возвращает True, если Health Connect доступен на устройстве."""
    if not ANDROID:
        return False
    try:
        sdk = _get_sdk_int()
        logger.info(f"HC: SDK level = {sdk}")

        if sdk >= 34:
            # Android 14+: пробуем встроенный HealthConnectManager
            try:
                autoclass('android.health.connect.HealthConnectManager')
                logger.info("HC: HealthConnectManager (API 34+) доступен")
                return True
            except Exception:
                logger.debug("HC: HealthConnectManager не найден, пробуем AndroidX...")

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


# ── Callback / Continuation обёртки (Java → Python) ──────────────────

if ANDROID:
    class _OutcomeReceiver(PythonJavaClass):
        """android.os.OutcomeReceiver — для HealthConnectManager (API 34+)."""
        __javainterfaces__ = ['android/os/OutcomeReceiver']
        __javacontext__ = 'app'

        def __init__(self):
            super().__init__()
            self._event = threading.Event()
            self._result = None
            self._error = None

        @java_method('(Ljava/lang/Object;)V')
        def onResult(self, result):
            self._result = result
            self._event.set()

        @java_method('(Ljava/lang/Throwable;)V')
        def onError(self, error):
            try:
                self._error = str(error.getMessage())
            except Exception:
                self._error = "Ошибка Health Connect"
            self._event.set()

        def get(self, timeout=30):
            """Блокирует поток до получения результата."""
            self._event.wait(timeout)
            if self._error:
                raise Exception(self._error)
            if self._result is None:
                raise Exception("Таймаут ожидания ответа Health Connect")
            return self._result

    class _KotlinContinuation(PythonJavaClass):
        """kotlin.coroutines.Continuation — для вызова suspend-функций
        AndroidX HealthConnectClient через pyjnius."""
        __javainterfaces__ = ['kotlin/coroutines/Continuation']
        __javacontext__ = 'app'

        def __init__(self):
            super().__init__()
            self._event = threading.Event()
            self._result = None
            self._error = None

        @java_method('()Lkotlin/coroutines/CoroutineContext;')
        def getContext(self):
            EmptyCC = autoclass('kotlin.coroutines.EmptyCoroutineContext')
            return EmptyCC.INSTANCE

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

        def get(self, timeout=30):
            self._event.wait(timeout)
            if self._error:
                raise Exception(self._error)
            if not self._event.is_set():
                raise Exception("Таймаут ожидания ответа Health Connect")
            return self._result


# ── Общие утилиты ────────────────────────────────────────────────────

def _instant_to_date_str(instant):
    """java.time.Instant → 'YYYY-MM-DD' (локальный часовой пояс)."""
    ZoneId = autoclass('java.time.ZoneId')
    zone = ZoneId.systemDefault()
    local_date = instant.atZone(zone).toLocalDate()
    return str(local_date.toString())


def _merge_to_db(db, steps_by_day, dist_by_day, kcal_by_day):
    """Объединяет данные HC с локальной БД (обновляет, если HC > local)."""
    all_days = set(steps_by_day) | set(dist_by_day) | set(kcal_by_day)
    merged = 0
    for day in sorted(all_days):
        hc_steps = steps_by_day.get(day, 0)
        hc_dist_km = dist_by_day.get(day, 0.0) / 1000.0   # м → км
        hc_kcal = kcal_by_day.get(day, 0.0)
        if hc_steps <= 0:
            continue
        local_steps, _, _ = db.get_activity_for_date(day)
        if hc_steps > local_steps:
            db.update_day_activity(day, hc_steps, hc_dist_km, hc_kcal)
            merged += 1
    return merged, len(all_days)


# ══════════════════════════════════════════════════════════════════════
#  Backend 1: HealthConnectManager (Android 14+ / API 34)
# ══════════════════════════════════════════════════════════════════════

def _platform_get_manager():
    PythonActivity = autoclass('org.kivy.android.PythonActivity')
    context = PythonActivity.mActivity.getApplicationContext()
    return context.getSystemService('health_connect')


def _platform_read_records(manager, record_class_name, start_ms, end_ms):
    Instant = autoclass('java.time.Instant')
    TimeFilterBuilder = autoclass(
        'android.health.connect.TimeInstantRangeFilter$Builder')
    RequestBuilder = autoclass(
        'android.health.connect.ReadRecordsRequestUsingFilters$Builder')
    JavaClass = autoclass('java.lang.Class')
    Executors = autoclass('java.util.concurrent.Executors')

    record_class = JavaClass.forName(record_class_name)
    time_filter = (TimeFilterBuilder()
                   .setStartTime(Instant.ofEpochMilli(int(start_ms)))
                   .setEndTime(Instant.ofEpochMilli(int(end_ms)))
                   .build())
    request = (RequestBuilder(record_class)
               .setTimeRangeFilter(time_filter)
               .build())

    executor = Executors.newSingleThreadExecutor()
    callback = _OutcomeReceiver()
    manager.readRecords(request, executor, callback)
    return callback.get(timeout=30)


def _platform_sync(db, days):
    """Синхронизация через HealthConnectManager (API 34+)."""
    manager = _platform_get_manager()
    if manager is None:
        raise Exception("HealthConnectManager недоступен")

    import time as _time
    end_ms = int(_time.time() * 1000)
    start_ms = end_ms - days * 24 * 3600 * 1000

    steps_by_day, dist_by_day, kcal_by_day = {}, {}, {}

    # Шаги
    resp = _platform_read_records(
        manager, 'android.health.connect.datatypes.StepsRecord',
        start_ms, end_ms)
    records = resp.getRecords()
    for i in range(records.size()):
        r = records.get(i)
        day = _instant_to_date_str(r.getStartTime())
        steps_by_day[day] = steps_by_day.get(day, 0) + int(r.getCount())

    # Дистанция
    resp = _platform_read_records(
        manager, 'android.health.connect.datatypes.DistanceRecord',
        start_ms, end_ms)
    records = resp.getRecords()
    for i in range(records.size()):
        r = records.get(i)
        day = _instant_to_date_str(r.getStartTime())
        dist_by_day[day] = dist_by_day.get(day, 0.0) + float(
            r.getDistance().getInMeters())

    # Калории
    resp = _platform_read_records(
        manager, 'android.health.connect.datatypes.TotalCaloriesBurnedRecord',
        start_ms, end_ms)
    records = resp.getRecords()
    for i in range(records.size()):
        r = records.get(i)
        day = _instant_to_date_str(r.getStartTime())
        kcal_by_day[day] = kcal_by_day.get(day, 0.0) + float(
            r.getEnergy().getInKilocalories())

    return steps_by_day, dist_by_day, kcal_by_day


# ══════════════════════════════════════════════════════════════════════
#  Backend 2: AndroidX HealthConnectClient (Android 9–13 / API 28–33)
#
#  readRecords() — suspend-функция Kotlin. В байткоде она принимает
#  дополнительный параметр Continuation и возвращает либо результат,
#  либо маркер COROUTINE_SUSPENDED. Мы реализуем Continuation через
#  pyjnius (_KotlinContinuation) и ждём callback resumeWith().
# ══════════════════════════════════════════════════════════════════════

_COROUTINE_SUSPENDED = 'COROUTINE_SUSPENDED'


def _is_suspended(result):
    """Проверяет, вернула ли suspend-функция маркер COROUTINE_SUSPENDED."""
    if result is None:
        return False
    try:
        return str(result.toString()) == _COROUTINE_SUSPENDED
    except Exception:
        return False


def _call_suspend(obj, method_name, *args):
    """Вызывает Kotlin suspend-функцию синхронно через Continuation."""
    cont = _KotlinContinuation()
    method = getattr(obj, method_name)
    result = method(*args, cont)

    if _is_suspended(result):
        return cont.get(timeout=30)
    if result is not None:
        return result

    # Результат None — возможно функция ещё работает, ждём continuation
    cont._event.wait(timeout=10)
    if cont._result is not None:
        return cont._result
    if cont._error:
        raise Exception(cont._error)
    raise Exception("Не удалось получить данные из Health Connect")


def _androidx_get_client():
    """Создаёт AndroidX HealthConnectClient (API 28–33)."""
    PythonActivity = autoclass('org.kivy.android.PythonActivity')
    context = PythonActivity.mActivity
    HCClient = autoclass(
        'androidx.health.connect.client.HealthConnectClient')
    # getOrCreate — @JvmStatic на companion object
    return HCClient.getOrCreate(context)


def _androidx_read_records(client, record_class_name, start_ms, end_ms):
    """Читает записи через AndroidX HealthConnectClient (suspend → sync)."""
    Instant = autoclass('java.time.Instant')
    TimeRangeFilter = autoclass(
        'androidx.health.connect.client.time.TimeRangeFilter')
    ReadRecordsRequest = autoclass(
        'androidx.health.connect.client.request.ReadRecordsRequest')
    JvmClassMappingKt = autoclass('kotlin.jvm.JvmClassMappingKt')
    JavaClass = autoclass('java.lang.Class')
    Collections = autoclass('java.util.Collections')

    # KClass для типа записи
    java_class = JavaClass.forName(record_class_name)
    kclass = JvmClassMappingKt.getKotlinClass(java_class)

    # TimeRangeFilter.between(startTime, endTime)  — @JvmStatic
    start_instant = Instant.ofEpochMilli(int(start_ms))
    end_instant = Instant.ofEpochMilli(int(end_ms))
    time_filter = TimeRangeFilter.between(start_instant, end_instant)

    # ReadRecordsRequest(KClass, TimeRangeFilter, Set, boolean, int, String)
    request = ReadRecordsRequest(
        kclass, time_filter, Collections.emptySet(), True, 1000, None)

    return _call_suspend(client, 'readRecords', request)


def _androidx_sync(db, days):
    """Синхронизация через AndroidX HealthConnectClient (API 28–33)."""
    client = _androidx_get_client()
    if client is None:
        raise Exception(
            "HealthConnectClient недоступен.\n"
            "Установите Health Connect из Google Play.")

    import time as _time
    end_ms = int(_time.time() * 1000)
    start_ms = end_ms - days * 24 * 3600 * 1000

    steps_by_day, dist_by_day, kcal_by_day = {}, {}, {}

    # Шаги
    resp = _androidx_read_records(
        client,
        'androidx.health.connect.client.records.StepsRecord',
        start_ms, end_ms)
    records = resp.getRecords()
    for i in range(records.size()):
        r = records.get(i)
        day = _instant_to_date_str(r.getStartTime())
        steps_by_day[day] = steps_by_day.get(day, 0) + int(r.getCount())

    # Дистанция
    resp = _androidx_read_records(
        client,
        'androidx.health.connect.client.records.DistanceRecord',
        start_ms, end_ms)
    records = resp.getRecords()
    for i in range(records.size()):
        r = records.get(i)
        day = _instant_to_date_str(r.getStartTime())
        dist_by_day[day] = dist_by_day.get(day, 0.0) + float(
            r.getDistance().getInMeters())

    # Калории
    resp = _androidx_read_records(
        client,
        'androidx.health.connect.client.records.TotalCaloriesBurnedRecord',
        start_ms, end_ms)
    records = resp.getRecords()
    for i in range(records.size()):
        r = records.get(i)
        day = _instant_to_date_str(r.getStartTime())
        kcal_by_day[day] = kcal_by_day.get(day, 0.0) + float(
            r.getEnergy().getInKilocalories())

    return steps_by_day, dist_by_day, kcal_by_day


# ── Публичная функция синхронизации ───────────────────────────────────

def sync_from_hc(db, days=30, on_done=None):
    """
    Читает шаги/дистанцию/калории из Health Connect за последние ``days``
    дней и объединяет с локальной БД.

    Обновляет только те записи, где HC даёт больше шагов, чем есть локально.

    Работает асинхронно. ``on_done(success: bool, message: str)`` вызывается
    в главном потоке Kivy.
    """
    if not ANDROID:
        if on_done:
            on_done(False, "Health Connect недоступен (не Android)")
        return

    def _background():
        try:
            sdk = _get_sdk_int()

            if sdk >= 34:
                steps, dist, kcal = _platform_sync(db, days)
            elif sdk >= 28:
                steps, dist, kcal = _androidx_sync(db, days)
            else:
                raise Exception("Health Connect требует Android 9+")

            merged, total = _merge_to_db(db, steps, dist, kcal)
            msg = f"Обновлено {merged} записей из {total} дней Health Connect"
            logger.info(f"HC sync: {msg}")

            if on_done:
                from kivy.clock import Clock
                Clock.schedule_once(lambda dt: on_done(True, msg), 0)

        except Exception as exc:
            logger.error(f"HC sync error: {exc}", exc_info=True)
            if on_done:
                from kivy.clock import Clock
                err = str(exc)
                Clock.schedule_once(lambda dt: on_done(False, err), 0)

    threading.Thread(target=_background, daemon=True).start()
