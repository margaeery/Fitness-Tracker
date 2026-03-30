__version__ = "0.1"
from kivy.app import App
from kivy.uix.screenmanager import ScreenManager, Screen, NoTransition
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.carousel import Carousel
from kivy.uix.button import Button
import os
    
# Импортируем классы и БД
from database import FitnessDB
from widgets import SetupScreen, MainScreen, StatsScreen

class FitnessApp(App):
    def build(self):
        # Инициализация базы данных
        self.db = FitnessDB()
        
        # Проверяем, настроен ли профиль пользователя
        metrics = self.db.get_latest_metrics()
        
        # Основной менеджер экранов
        self.root_manager = ScreenManager(transition=NoTransition())
        
        if not metrics:
            # Если данных нет, добавляем экран первичной настройки
            setup_screen = SetupScreen(name='setup')
            self.root_manager.add_widget(setup_screen)
        else:
            # Если данные есть, создаем основной интерфейс с навигацией
            main_layout = self.create_main_layout()
            self.root_manager.add_widget(main_layout)
            
        return self.root_manager

    def restart_with_nav(self):
        """Метод для переключения с экрана настройки на главный экран"""
        self.root_manager.clear_widgets()
        self.root_manager.add_widget(self.create_main_layout())
        self.root_manager.current = 'nav_screen'

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
        nav = GridLayout(cols=2, size_hint_y=None, height=65)


        self.btn_main = Button(
            text="Главная", 
            background_normal='', 
            background_color=(0.12, 0.58, 0.95, 1) # Активный цвет
        )

        self.btn_stats = Button(
            text="Графики", 
            background_normal='', 
            background_color=(0.3, 0.3, 0.3, 1) # Темный цвет
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
        """Закрываем базу данных при выходе из приложения"""
        if hasattr(self, 'db'):
            self.db.close()

if __name__ == '__main__':
    FitnessApp().run()