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
from step_counter import StepCounter, ANDROID

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

        # Инициализация счётчика шагов (датчик подключается позже)
        self.step_counter = StepCounter(self.db)

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
            # Запускаем датчик шагов (запрос разрешений на Android)
            self._init_step_counter()

        return self.root_manager

    def restart_with_nav(self):
        """Метод для переключения с экрана настройки на главный экран"""
        logger.info("Переключение на главный экран (после настройки профиля)")
        self.root_manager.clear_widgets()
        self.root_manager.add_widget(self.create_main_layout())
        self.root_manager.current = 'nav_screen'
        # Запускаем датчик после первичной настройки
        self._init_step_counter()

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
        """Закрываем базу данных и датчик при выходе из приложения"""
        logger.info("═══ Остановка FitnessApp ═══")
        if hasattr(self, 'step_counter'):
            self.step_counter.stop()
        if hasattr(self, 'db'):
            self.db.close()

    def on_pause(self):
        """Приложение сворачивается — приостанавливаем датчик."""
        logger.info("App → on_pause")
        if hasattr(self, 'step_counter'):
            self.step_counter.stop()
        return True  # Обязательно True, иначе Android убьёт процесс

    def on_resume(self):
        """Приложение возвращается — перезапускаем датчик и обновляем UI."""
        logger.info("App → on_resume")
        self._start_step_counter()
        if hasattr(self, 'main_screen'):
            self.main_screen.on_enter()

    # Датчик шагов

    def _init_step_counter(self):
        """Запрашивает разрешение ACTIVITY_RECOGNITION и запускает датчик."""
        if not ANDROID:
            logger.info("Не Android — датчик шагов не запускается")
            return

        try:
            from android.permissions import request_permissions, check_permission
            perm = 'android.permission.ACTIVITY_RECOGNITION'

            if check_permission(perm):
                logger.info("Разрешение ACTIVITY_RECOGNITION уже получено")
                self._start_step_counter()
            else:
                logger.info("Запрашиваем разрешение ACTIVITY_RECOGNITION")
                request_permissions([perm], self._on_permission_result)
        except Exception as e:
            logger.error(f"Ошибка запроса разрешений: {e}", exc_info=True)
            # На старых API разрешение может быть не нужно — пробуем запустить
            self._start_step_counter()

    def _on_permission_result(self, permissions, grants):
        """Callback после ответа пользователя на запрос разрешений."""
        if grants and all(grants):
            logger.info("Разрешение ACTIVITY_RECOGNITION получено")
            self._start_step_counter()
        else:
            logger.warning("Разрешение ACTIVITY_RECOGNITION отклонено — "
                           "подсчёт шагов через датчик невозможен")

    def _start_step_counter(self):
        """Регистрирует датчик шагов."""
        if hasattr(self, 'step_counter') and not self.step_counter.is_running:
            self.step_counter.start(ui_callback=self._on_steps_update)

    def _on_steps_update(self, steps):
        """Callback от датчика — обновляем UI главного экрана."""
        if hasattr(self, 'main_screen') and hasattr(self, 'carousel'):
            if self.carousel.index == 0:
                self.main_screen.on_enter()

if __name__ == '__main__':
    FitnessApp().run()