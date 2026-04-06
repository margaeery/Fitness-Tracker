# from kivy.config import Config
# # Настройки окна для тестирования на компьютере
# Config.set('graphics', 'width', '360')
# Config.set('graphics', 'height', '800')
# #Config.set('graphics', 'resizable', False)

import logging
import os

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

    # ─── Разрешения и запуск сервиса ─────────────────────────────────

    def _request_permissions_and_start_service(self):
        """Запрашивает разрешения последовательно, затем запускает сервис.
        Порядок: 1) шаги → 2) уведомления → 3) popup батареи → 4) системный запрос батареи."""
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
        except Exception as e:
            logger.error(f"Ошибка запуска сервиса: {e}", exc_info=True)

    # ─── Периодическое обновление UI ─────────────────────────────────

    def _start_ui_refresh(self):
        """Запускает таймер обновления UI (каждые 30 секунд)."""
        self._stop_ui_refresh()
        # Немедленное обновление при заходе
        if hasattr(self, 'main_screen'):
            self.main_screen.on_enter()
            logger.debug("Экран обновлён сразу")
        self._refresh_event = Clock.schedule_interval(self._refresh_ui, 30)
        logger.debug("UI refresh timer запущен (30s)")

    def _stop_ui_refresh(self):
        """Останавливает таймер обновления UI."""
        if hasattr(self, '_refresh_event') and self._refresh_event:
            self._refresh_event.cancel()
            self._refresh_event = None

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

if __name__ == '__main__':
    FitnessApp().run()