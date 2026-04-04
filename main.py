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
from database import FitnessDB
from widgets import SetupScreen, MainScreen, StatsScreen

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
        self._stop_ui_refresh()
        if hasattr(self, 'db'):
            self.db.close()

    def on_pause(self):
        """Приложение сворачивается — сервис продолжает считать шаги."""
        logger.info("App → on_pause")
        self._stop_ui_refresh()
        return True  # Обязательно True, иначе Android убьёт процесс

    def on_resume(self):
        """Приложение возвращается — обновляем UI из БД."""
        logger.info("App → on_resume")
        self._start_ui_refresh()
        if hasattr(self, 'main_screen'):
            self.main_screen.on_enter()

    # ─── Разрешения и запуск сервиса ─────────────────────────────────

    def _request_permissions_and_start_service(self):
        """Запрашивает все необходимые разрешения, затем запускает сервис."""
        if not ANDROID:
            logger.info("Не Android — сервис не запускается")
            return

        try:
            from android.permissions import request_permissions, check_permission

            perms_needed = []

            perm_activity = 'android.permission.ACTIVITY_RECOGNITION'
            if not check_permission(perm_activity):
                perms_needed.append(perm_activity)

            perm_notif = 'android.permission.POST_NOTIFICATIONS'
            if not check_permission(perm_notif):
                perms_needed.append(perm_notif)

            if perms_needed:
                logger.info(f"Запрашиваем разрешения: {perms_needed}")
                request_permissions(perms_needed, self._on_permissions_result)
            else:
                logger.info("Все разрешения уже получены")
                self._start_service()

        except Exception as e:
            logger.error(f"Ошибка запроса разрешений: {e}", exc_info=True)
            self._start_service()

    def _on_permissions_result(self, permissions, grants):
        """Callback после ответа пользователя на все запросы разрешений."""
        for perm, grant in zip(permissions, grants):
            name = perm.split('.')[-1]
            if grant:
                logger.info(f"Разрешение {name} получено")
            else:
                logger.warning(f"Разрешение {name} отклонено")
        # Запускаем сервис в любом случае —
        # на старых API разрешения могут быть не нужны
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
            logger.info(f"Сервис запущен: {service_name}")
            # Начинаем обновлять UI из БД
            self._start_ui_refresh()
        except Exception as e:
            logger.error(f"Ошибка запуска сервиса: {e}", exc_info=True)

    # ─── Периодическое обновление UI ─────────────────────────────────

    def _start_ui_refresh(self):
        """Запускает таймер обновления UI (каждые 10 секунд)."""
        self._stop_ui_refresh()
        self._refresh_event = Clock.schedule_interval(self._refresh_ui, 10)
        logger.debug("UI refresh timer запущен")

    def _stop_ui_refresh(self):
        """Останавливает таймер обновления UI."""
        if hasattr(self, '_refresh_event') and self._refresh_event:
            self._refresh_event.cancel()
            self._refresh_event = None

    def _refresh_ui(self, dt):
        """Перечитывает данные из БД и обновляет главный экран."""
        if hasattr(self, 'main_screen') and hasattr(self, 'carousel'):
            if self.carousel.index == 0:
                self.main_screen.on_enter()

if __name__ == '__main__':
    FitnessApp().run()