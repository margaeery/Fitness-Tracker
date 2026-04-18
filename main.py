# from kivy.config import Config
# # Настройки окна для тестирования на компьютере
# Config.set('graphics', 'width', '360')
# Config.set('graphics', 'height', '800')
# #Config.set('graphics', 'resizable', False)

import logging
import os
import time as _time

from kivy.app import App
from kivy.uix.screenmanager import ScreenManager, Screen, NoTransition
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.carousel import Carousel
from kivy.uix.button import Button
from kivy.metrics import dp, sp
from kivy.clock import Clock

# Импортируем классы и БД
from database import FitnessDB, DB_PATH
from widgets import SetupScreen, MainScreen, StatsScreen
import health_connect as hc

# Файл-флаг для сигнализации сервису о том, что приложение на экране
import os as _os
FOREGROUND_FLAG = _os.path.join(DB_PATH, '.app_foreground')

# Проверка платформы
ANDROID = False
try:
    from jnius import autoclass
    ANDROID = True
except ImportError:
    pass

# Настройка логирования
def setup_logging():
    """Настраивает логирование приложения.
    На Android вывод попадает в logcat (adb logcat -s python)."""
    root_logger = logging.getLogger('FitnessTracker')
    root_logger.setLevel(logging.DEBUG)

    handler = logging.StreamHandler()
    handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter(
        '%(asctime)s [%(name)s] %(levelname)s: %(message)s',
        datefmt='%H:%M:%S',
    )
    handler.setFormatter(formatter)
    root_logger.addHandler(handler)
    return root_logger

logger = setup_logging()


class FitnessApp(App):
    def build(self):
        logger.info("═══ Запуск FitnessApp ═══")

        # Инициализация базы данных
        self.db = FitnessDB()
        self._refresh_event = None
        self._service_started = False

        # Проверяем, настроен ли профиль пользователя
        metrics = self.db.get_latest_metrics()

        # Основной менеджер экранов
        self.root_manager = ScreenManager(transition=NoTransition())

        if not metrics:
            # Если данных нет, добавляем экран первичной настройки
            logger.info("Профиль не настроен — показываем экран настройки")
            setup_screen = SetupScreen(name='setup')
            self.root_manager.add_widget(setup_screen)
        else:
            # Если данные есть, создаем основной интерфейс с навигацией
            logger.info(f"Профиль найден: weight={metrics[0]}, "
                        f"height={metrics[1]}, goal={metrics[2]}")
            main_layout = self.create_main_layout()
            self.root_manager.add_widget(main_layout)
            # Запрашиваем разрешения и стартуем фоновый сервис
            self._request_permissions_and_start_service()

        return self.root_manager

    def restart_with_nav(self):
        """Метод для переключения с экрана настройки на главный экран"""
        logger.info("Переключение на главный экран (после настройки профиля)")
        self.root_manager.clear_widgets()
        self.root_manager.add_widget(self.create_main_layout())
        self.root_manager.current = 'nav_screen'
        # Запрашиваем разрешения и стартуем фоновый сервис
        self._request_permissions_and_start_service()

    def create_main_layout(self):
        """Создает экран с Carousel (слайдами) и нижней панелью навигации"""
        nav_screen = Screen(name='nav_screen')
        layout = BoxLayout(orientation='vertical')
        
        # Создаем слайды
        self.carousel = Carousel(direction='right')
        
        # Сохраняем ссылки на экраны для доступа к их методам
        self.main_screen = MainScreen(name='main')
        self.stats_screen = StatsScreen(name='stats')
        
        self.carousel.add_widget(self.main_screen)
        self.carousel.add_widget(self.stats_screen)
        
        # Нижняя панель навигации
        nav_bar = self.create_nav_bar()
        
        # Собираем всё вместе
        layout.add_widget(self.carousel)
        layout.add_widget(nav_bar)
        nav_screen.add_widget(layout)
        
        # Привязываем обновление кнопок к перелистыванию слайдов
        self.carousel.bind(index=self.update_nav_buttons)
        
        # Вызываем обновление данных на главном экране при запуске
        self.main_screen.on_enter()
        
        return nav_screen

    def create_nav_bar(self):
        """Создает нижние кнопки навигации"""
        from kivy.uix.gridlayout import GridLayout
        nav = GridLayout(cols=2, size_hint_y=None, height=dp(64))


        self.btn_main = Button(
            text="Главная", 
            background_normal='', 
            background_color=(0.12, 0.58, 0.95, 1)
        )

        self.btn_stats = Button(
            text="Графики", 
            background_normal='', 
            background_color=(0.3, 0.3, 0.3, 1)
        )
        
        self.btn_main.bind(on_release=lambda x: self.change_tab(0))
        self.btn_stats.bind(on_release=lambda x: self.change_tab(1))
        
        nav.add_widget(self.btn_main)
        nav.add_widget(self.btn_stats)
        return nav

    def change_tab(self, index):
        """Переключает слайд при нажатии на кнопку"""
        if index < len(self.carousel.slides):
            self.carousel.load_slide(self.carousel.slides[index])

    def update_nav_buttons(self, instance, value):
        """Меняет цвет кнопок в зависимости от активного слайда"""
        if value == 0:
            self.btn_main.background_color = (0.12, 0.58, 0.95, 1)
            self.btn_stats.background_color = (0.3, 0.3, 0.3, 1)
            self.main_screen.on_enter() # Обновляем данные при возврате на главную
        else:
            self.btn_main.background_color = (0.3, 0.3, 0.3, 1)
            self.btn_stats.background_color = (0.12, 0.58, 0.95, 1)
            self.stats_screen.on_enter() # Обновляем графики при переходе

    def on_stop(self):
        """Закрываем базу данных при выходе. Сервис продолжает работать."""
        logger.info("═══ Остановка FitnessApp ═══")
        self._set_foreground_flag(False)
        self._stop_ui_refresh()
        if hasattr(self, 'db'):
            self.db.close()

    def on_pause(self):
        """Приложение сворачивается — сервис продолжает считать шаги."""
        logger.info("App → on_pause")
        self._set_foreground_flag(False)
        self._stop_ui_refresh()
        return True  # Обязательно True, иначе Android убьёт процесс

    def on_resume(self):
        """Приложение возвращается — обновляем UI или продвигаем цепочку разрешений."""
        logger.info("App → on_resume")

        # Проверяем, ждали ли мы возврата из HC permission screen
        if getattr(self, '_hc_waiting_permissions', False):
            self._hc_waiting_permissions = False
            # Не проверяем has_read_permissions() — она ненадёжна для HC.
            # Просто пробуем sync — если разрешения даны, данные загрузятся.
            logger.info("HC: возврат из экрана разрешений, пробуем sync")
            Clock.schedule_once(lambda dt: self._hc_sync(), 0.3)
            return

        phase = getattr(self, '_perm_phase', None)
        if phase in ('awaiting_activity', 'awaiting_notification'):
            # Диалог разрешения закрылся — продвигаем цепочку
            self._try_advance()
            return
        if phase == 'awaiting_battery':
            # Системный диалог батареи закрылся — запускаем сервис
            self._perm_phase = 'done'
            Clock.schedule_once(lambda dt: self._start_service(), 0.3)
            return

        if not self._service_started:
            return
        self._set_foreground_flag(True)
        self._start_ui_refresh()
        # Тихая авто-синхронизация HC при возврате из фона (один раз)
        self._hc_auto_sync()

    # Разрешения и запуск сервиса

    def _request_permissions_and_start_service(self):
        """Запрашивает разрешения последовательно, затем запускает сервис."""
        if not ANDROID:
            logger.info("Не Android — сервис не запускается")
            return

        self._perm_phase = 'start'
        self._advancing = False
        self._asked_perms = set()  # уже запрошенные — не спрашиваем повторно
        self._advance_permissions()

    def _try_advance(self):
        """Безопасно продвигает цепочку. Защита от двойного вызова."""
        if getattr(self, '_advancing', False):
            logger.debug("_try_advance: уже в процессе, пропускаем")
            return
        Clock.schedule_once(lambda dt: self._advance_permissions(), 0.3)

    def _advance_permissions(self):
        """Проверяет какие разрешения нужны и запрашивает следующее."""
        if getattr(self, '_advancing', False):
            return
        self._advancing = True
        try:
            from android.permissions import request_permissions, check_permission

            # 1. ACTIVITY_RECOGNITION
            perm_activity = 'android.permission.ACTIVITY_RECOGNITION'
            if not check_permission(perm_activity) and perm_activity not in self._asked_perms:
                logger.info("Запрашиваем ACTIVITY_RECOGNITION")
                self._perm_phase = 'awaiting_activity'
                self._asked_perms.add(perm_activity)
                self._advancing = False
                request_permissions([perm_activity], self._on_perm_result)
                return

            # 2. POST_NOTIFICATIONS
            perm_notif = 'android.permission.POST_NOTIFICATIONS'
            if not check_permission(perm_notif) and perm_notif not in self._asked_perms:
                logger.info("Запрашиваем POST_NOTIFICATIONS")
                self._perm_phase = 'awaiting_notification'
                self._asked_perms.add(perm_notif)
                self._advancing = False
                request_permissions([perm_notif], self._on_perm_result)
                return

            # 3. Все runtime-разрешения обработаны — переходим к батарее
            logger.info("Runtime-разрешения обработаны")
            self._perm_phase = 'battery'
            self._advancing = False
            self._request_battery_and_start()

        except Exception as e:
            logger.error(f"Ошибка запроса разрешений: {e}", exc_info=True)
            self._perm_phase = 'done'
            self._advancing = False
            self._start_service()

    def _on_perm_result(self, permissions, grants):
        """Callback от Android. Логирует + продвигает цепочку."""
        for perm, grant in zip(permissions, grants):
            name = perm.split('.')[-1]
            logger.info(f"{name}: {'получено' if grant else 'отклонено'}")
        # Продвигаем цепочку из callback'а (если on_resume не сделал этого)
        self._try_advance()

    def _request_battery_and_start(self):
        """Показывает предупреждение об оптимизации батареи, затем запускает сервис."""
        if not ANDROID:
            self._start_service()
            return

        try:
            from jnius import autoclass as _ac
            context = _ac('org.kivy.android.PythonActivity').mActivity.getApplicationContext()
            pm = context.getSystemService('power')
            pkg = context.getPackageName()

            if not pm.isIgnoringBatteryOptimizations(pkg):
                self._show_battery_popup()
            else:
                logger.debug("Оптимизация батареи уже отключена")
                self._start_service()
        except Exception as e:
            logger.warning(f"Проверка оптимизации батареи: {e}")
            self._start_service()

    def _show_battery_popup(self):
        """Показывает popup с объяснением зачем отключать оптимизацию батареи."""
        from kivy.uix.popup import Popup
        from kivy.uix.label import Label
        from kivy.uix.button import Button as KButton
        from kivy.uix.boxlayout import BoxLayout as BL

        content = BL(orientation='vertical', padding=dp(10), spacing=dp(10))
        content.add_widget(Label(
            text='Для подсчёта шагов в фоновом режиме\n'
                 '(при свёрнутом или закрытом приложении)\n'
                 'необходимо снять ограничения на\n'
                 'использование батареи.\n\n'
                 'Нажмите «Разрешить» в следующем окне.',
            halign='center',
            valign='middle',
        ))
        btn = KButton(text='Понятно', size_hint_y=None, height=dp(48))
        content.add_widget(btn)

        popup = Popup(
            title='Работа в фоновом режиме',
            content=content,
            size_hint=(0.85, 0.45),
            auto_dismiss=False,
        )

        def _on_ok(instance):
            popup.dismiss()
            self._do_battery_exemption()

        btn.bind(on_release=_on_ok)
        popup.open()

    def _do_battery_exemption(self):
        """Запрашивает системное исключение из оптимизации батареи."""
        try:
            from jnius import autoclass as _ac
            Settings = _ac('android.provider.Settings')
            Intent = _ac('android.content.Intent')
            Uri = _ac('android.net.Uri')

            activity = _ac('org.kivy.android.PythonActivity').mActivity
            pkg = activity.getApplicationContext().getPackageName()

            intent = Intent(
                Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS
            )
            intent.setData(Uri.parse(f'package:{pkg}'))
            # on_resume вызовет _start_service когда диалог закроется
            self._perm_phase = 'awaiting_battery'
            activity.startActivity(intent)
            logger.info("Запрошено исключение из оптимизации батареи")
        except Exception as e:
            logger.warning(f"Не удалось запросить отключение оптимизации: {e}")
            # Если не удалось открыть диалог — запускаем сервис напрямую
            self._perm_phase = 'done'
            self._start_service()

    def _start_service(self):
        """Запускает фоновый сервис подсчёта шагов."""
        if not ANDROID:
            return
        try:
            from jnius import autoclass as _ac
            activity = _ac('org.kivy.android.PythonActivity').mActivity
            context = activity.getApplicationContext()

            # Имя Java-класса сервиса (генерируется buildozer/p4a)
            service_name = f'{context.getPackageName()}.ServiceStepservice'
            service_class = _ac(service_name)
            service_class.start(activity, '')
            self._service_started = True
            logger.info(f"Сервис запущен: {service_name}")
            # Сигнализируем сервису: приложение на экране
            self._set_foreground_flag(True)
            # Начинаем обновлять UI из БД
            self._start_ui_refresh()
            # Тихая автосинхронизация с HC при запуске (если разрешения уже есть)
            self._hc_auto_sync()
        except Exception as e:
            logger.error(f"Ошибка запуска сервиса: {e}", exc_info=True)

    # Периодическое обновление UI 

    def _start_ui_refresh(self):
        """Запускает таймер обновления UI (каждые 15 секунд) и HC sync (каждые 20 секунд)."""
        self._stop_ui_refresh()
        # Немедленное обновление при заходе
        if hasattr(self, 'main_screen'):
            self.main_screen.on_enter()
            logger.debug("Экран обновлён сразу")
        self._refresh_event = Clock.schedule_interval(self._refresh_ui, 15)
        # Периодическая HC синхронизация каждые 20с при активном экране
        self._hc_periodic_event = Clock.schedule_interval(
            lambda dt: self._hc_auto_sync(), 20)
        logger.debug("UI refresh (15s) + HC periodic sync (20s) запущены")

    def _stop_ui_refresh(self):
        """Останавливает таймеры обновления UI и HC sync."""
        if hasattr(self, '_refresh_event') and self._refresh_event:
            self._refresh_event.cancel()
            self._refresh_event = None
        if hasattr(self, '_hc_periodic_event') and self._hc_periodic_event:
            self._hc_periodic_event.cancel()
            self._hc_periodic_event = None

    def _set_foreground_flag(self, active):
        """Создаёт/удаляет файл-флаг для сигнализации сервису."""
        try:
            if active:
                with open(FOREGROUND_FLAG, 'w') as f:
                    f.write('1')
                logger.debug("Foreground flag → ON")
            else:
                if _os.path.exists(FOREGROUND_FLAG):
                    _os.remove(FOREGROUND_FLAG)
                logger.debug("Foreground flag → OFF")
        except Exception as e:
            logger.error(f"Ошибка foreground flag: {e}")

    def _refresh_ui(self, dt):
        """Перечитывает данные из БД и обновляет главный экран."""
        if hasattr(self, 'main_screen') and hasattr(self, 'carousel'):
            if self.carousel.index == 0:
                self.main_screen.on_enter()

    # ── Health Connect ────────────────────────────────────────────────────

    def hc_connect(self):
        """Нажатие кнопки Health Connect.
        Пробуем синхронизацию напрямую (30 дней).
        Если нет разрешений — HC сам покажет ошибку, и мы откроем экран разрешений."""
        if not ANDROID:
            self._hc_show_popup("Недоступно",
                "Health Connect работает только на Android.")
            return

        if not hc.is_available():
            sdk = 0
            try:
                from jnius import autoclass as _ac
                sdk = _ac('android.os.Build$VERSION').SDK_INT
            except Exception:
                pass
            self._hc_show_popup("Не найден",
                f"Health Connect не найден.\n"
                f"(Android API {sdk})\n"
                f"Установите Health Connect\n"
                f"из Google Play и повторите.")
            return

        # Проверяем разрешения: если есть — синхронизируем, если нет — запрашиваем
        if hc.has_read_permissions():
            self._hc_sync()
        else:
            self._hc_request_permissions()

    def _hc_request_permissions(self):
        """Запрашивает разрешения Health Connect.
        API 34+: HC — часть системы, используем requestPermissions() +
                 платформенный HealthConnectManager (проверяет Android perms).
        API < 34: HC — отдельное приложение, нужен intent для открытия
                  экрана разрешений HC-приложения."""
        logger.info("Запрашиваем разрешения Health Connect")
        try:
            from jnius import autoclass as _ac
            sdk = _ac('android.os.Build$VERSION').SDK_INT

            if sdk >= 34:
                # API 34+: стандартный запрос runtime-разрешений
                self._hc_request_permissions_runtime()
            else:
                # API < 34: через intent HC-приложения
                self._hc_request_permissions_intent()
        except Exception as e:
            logger.error(f"Ошибка запроса HC permissions: {e}")
            self._hc_show_popup("Ошибка", str(e))

    def _hc_request_permissions_runtime(self):
        """API 34+: запрашиваем HC-разрешения как стандартные runtime permissions.

        На API 34+ HC — часть системы. Мы используем платформенный
        HealthConnectManager (не SDK content provider), который проверяет
        стандартные Android runtime permissions. Поэтому requestPermissions()
        здесь — правильный и достаточный подход.

        Fallback: если requestPermissions() не сработает — открываем
        настройки HC через intent."""
        logger.info("HC: requestPermissions (runtime) для API 34+")
        from android.permissions import request_permissions
        self._hc_waiting_permissions = True
        request_permissions(
            ['android.permission.health.READ_STEPS'],
            self._on_hc_runtime_perm_result)

    def _on_hc_runtime_perm_result(self, permissions, grants):
        """Callback после стандартного requestPermissions (API 34+)."""
        self._hc_waiting_permissions = False
        granted = all(grants)
        logger.info(f"HC runtime permissions result: {list(zip(permissions, grants))}")
        if granted:
            Clock.schedule_once(lambda dt: self._hc_sync(), 0.3)
        else:
            self._hc_show_popup("Доступ отклонён",
                "Разрешение на чтение шагов\nне получено.\n\n"
                "Предоставьте доступ в\nНастройки → Приложения →\n"
                "FitnessTracker → Разрешения.")

    def _hc_request_permissions_intent(self):
        """API < 34: открываем экран разрешений через intent HC-приложения."""
        from jnius import autoclass as _ac
        Intent = _ac('android.content.Intent')
        PythonActivity = _ac('org.kivy.android.PythonActivity')
        activity = PythonActivity.mActivity
        pkg = activity.getPackageName()
        pm = activity.getPackageManager()

        # Список intents для попытки (в порядке приоритета)
        intents = []

        # Через HC-приложение
        i = Intent('androidx.health.ACTION_MANAGE_HEALTH_PERMISSIONS')
        i.putExtra('android.intent.extra.PACKAGE_NAME', pkg)
        intents.append(i)

        # Запасной: общие настройки HC
        intents.append(Intent('androidx.health.ACTION_HEALTH_CONNECT_SETTINGS'))

        for intent in intents:
            if intent.resolveActivity(pm) is not None:
                self._hc_waiting_permissions = True
                activity.startActivity(intent)
                self._hc_show_popup(
                    "Разрешения",
                    "Откроется Health Connect.\n"
                    "Включите доступ к данным\n"
                    "для FitnessTracker.\n\n"
                    "Затем вернитесь в приложение.")
                return

        self._hc_show_popup(
            "Ошибка",
            "Не удалось открыть\n"
            "настройки Health Connect.\n"
            "Откройте HC вручную и\n"
            "выдайте разрешения.")

    def _hc_sync(self):
        """Запускает синхронизацию данных из Health Connect."""
        self._hc_set_btn_text("Загрузка...")
        hc.sync_from_hc(self.db, days=30, on_done=self._hc_sync_done)

    def _hc_sync_done(self, success, message):
        """Вызывается когда синхронизация завершена."""
        self._hc_set_btn_text("Health Connect")
        if success:
            self._hc_auto_disabled = False
            self._hc_show_popup("Health Connect", message)
            # Обновляем оба экрана (главный + графики)
            if hasattr(self, 'main_screen'):
                self.main_screen.on_enter()
            if hasattr(self, 'stats_screen'):
                self.stats_screen.update_stats()
            self._check_goal_after_hc()
        else:
            # Понятное сообщение при отсутствии разрешений
            is_perm = any(w in message for w in ('SecurityException', 'PERMISSION', 'permission'))
            if is_perm:
                self._hc_show_popup("Доступ отклонён",
                    "Разрешения Health Connect\nне получены.\n\n"
                    "Откройте настройки HC\nи выдайте доступ.")
            else:
                self._hc_show_popup("Ошибка", message)

    def _hc_auto_sync(self):
        """Тихая синхронизация (1 день), если HC доступен."""
        if not ANDROID:
            return
        if getattr(self, '_hc_auto_disabled', False):
            return
        if getattr(self, '_hc_syncing', False):
            return
        try:
            if hc.is_available():
                self._hc_syncing = True
                logger.debug("HC auto-sync (1 день)")
                hc.sync_from_hc(self.db, days=1,
                                 on_done=self._hc_auto_sync_done)
        except Exception as e:
            self._hc_syncing = False
            logger.warning(f"HC auto-sync failed: {e}")

    def _hc_auto_sync_done(self, success, message):
        """Тихое завершение авто-синхронизации — обновляем UI."""
        self._hc_syncing = False
        logger.info(f"HC auto-sync: success={success}, {message}")
        if success:
            self._hc_auto_disabled = False
            if hasattr(self, 'main_screen'):
                self.main_screen.on_enter()
            # Обновляем графики если они видимы
            if hasattr(self, 'stats_screen') and hasattr(self, 'carousel'):
                if self.carousel.index == 1:
                    self.stats_screen.update_stats()
            self._check_goal_after_hc()
        else:
            is_perm = any(w in message for w in ('SecurityException', 'PERMISSION', 'permission'))
            if is_perm:
                self._hc_auto_disabled = True
                logger.info("HC auto-sync отключен: нет разрешений")

    def _check_goal_after_hc(self):
        """Проверяет достижение цели после HC-синхронизации.
        Использует goal_state в БД для однократного уведомления."""
        try:
            from datetime import datetime as _dt
            today = _dt.now().strftime('%Y-%m-%d')
            if self.db.get_goal_achieved(today):
                return  # уже уведомлено сегодня
            metrics = self.db.get_latest_metrics()
            if not metrics:
                return
            goal = int(metrics[2])
            if goal <= 0:
                return
            today_steps = self.db.get_today_steps()
            if today_steps >= goal:
                self.db.set_goal_achieved(today)
                logger.info(f"HC sync: цель достигнута {today_steps}/{goal}")
                self._send_goal_notification()
        except Exception as e:
            logger.warning(f"Goal check after HC failed: {e}")

    def _send_goal_notification(self):
        """Отправляет уведомление о достижении цели через Java Notification API."""
        try:
            from jnius import autoclass as _ac
            Context = _ac('android.content.Context')
            NotificationBuilder = _ac('android.app.Notification$Builder')
            NotificationManager = _ac('android.app.NotificationManager')
            NotificationChannel = _ac('android.app.NotificationChannel')

            activity = _ac('org.kivy.android.PythonActivity').mActivity
            context = activity.getApplicationContext()
            nm = context.getSystemService(Context.NOTIFICATION_SERVICE)

            channel_id = 'fitness_goals'
            channel = NotificationChannel(
                channel_id, 'Достижение целей',
                NotificationManager.IMPORTANCE_HIGH,
            )
            nm.createNotificationChannel(channel)

            builder = NotificationBuilder(context, channel_id)
            builder.setContentTitle('Цель достигнута!')
            builder.setContentText('Поздравляем! Вы выполнили дневную цель по шагам!')
            builder.setSmallIcon(context.getApplicationInfo().icon)
            builder.setAutoCancel(True)
            nm.notify(1002, builder.build())
            logger.info('Goal notification sent from main app')
        except Exception as e:
            logger.warning(f'Goal notification failed: {e}')

    def _hc_set_btn_text(self, text):
        """Меняет текст кнопки Health Connect в ActionBar."""
        try:
            self.main_screen.ids.hc_btn.text = text
        except Exception:
            pass  # не критично если кнопка недоступна

    def _hc_show_popup(self, title, message):
        """Показывает информационный попап с результатом HC операции.
        Безопасно вызывать из любого потока — попап создаётся в главном."""
        def _do_popup(dt):
            from kivy.uix.popup import Popup
            from kivy.uix.label import Label
            from kivy.uix.button import Button as KButton
            from kivy.uix.boxlayout import BoxLayout as BL

            content = BL(orientation='vertical', padding=dp(10), spacing=dp(10))
            content.add_widget(Label(
                text=message,
                halign='center',
                valign='middle',
            ))
            btn = KButton(text='ОК', size_hint_y=None, height=dp(48))
            content.add_widget(btn)

            popup = Popup(
                title=title,
                content=content,
                size_hint=(0.85, 0.4),
            )
            btn.bind(on_release=popup.dismiss)
            popup.open()

        Clock.schedule_once(_do_popup, 0)

if __name__ == '__main__':
    FitnessApp().run()