from kivy.uix.screenmanager import Screen
from kivy.uix.popup import Popup
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.widget import Widget
from kivy.properties import NumericProperty, ListProperty, StringProperty
from kivy.graphics import Color, RoundedRectangle, Rectangle
from kivy.core.text import Label as CoreLabel
from kivy.app import App
from calculator import FitnessCalculator
from datetime import datetime, timedelta
import calendar

MONTHS_RU = {
    1: "Январь", 2: "Февраль", 3: "Март", 4: "Апрель",
    5: "Май", 6: "Июнь", 7: "Июль", 8: "Август",
    9: "Сентябрь", 10: "Октябрь", 11: "Ноябрь", 12: "Декабрь"
}

class ErrorPopup(Popup):
    def __init__(self, message, **kwargs):
        super().__init__(**kwargs)
        self.title = "Ошибка"
        self.size_hint = (0.8, 0.3)
        layout = BoxLayout(orientation='vertical', padding=10, spacing=10)
        layout.add_widget(Label(text=message, halign='center'))
        btn = Button(text="ОК", size_hint=(1, 0.4))
        btn.bind(on_release=self.dismiss)
        layout.add_widget(btn)
        self.content = layout

class SetupScreen(Screen):
    def save_profile(self):
        try:
            w = float(self.ids.weight_input.text)
            h = float(self.ids.height_input.text)
            g = int(self.ids.goal_input.text)
            if w <= 0 or h <= 0 or g <= 0: raise ValueError
            app = App.get_running_app()
            app.db.save_user_metrics(w, h, g)
            app.restart_with_nav()
        except ValueError:
            ErrorPopup(message="Введите корректные числа!").open()

class SettingsPopup(Popup):
    def __init__(self, current_data, **kwargs):
        super().__init__(**kwargs)
        self.title = "Настройки"
        self.size_hint = (0.9, 0.6)
        weight, height, goal = current_data
        self.ids.weight_input.text = str(weight)
        self.ids.height_input.text = str(height)
        self.ids.goal_input.text = str(goal)

    def update_profile(self):
        try:
            w = float(self.ids.weight_input.text)
            h = float(self.ids.height_input.text)
            g = int(self.ids.goal_input.text)
            app = App.get_running_app()
            app.db.save_user_metrics(w, h, g)
            app.main_screen.on_enter()
            self.dismiss()
        except ValueError:
            ErrorPopup(message="Ошибка в данных").open()

class MainScreen(Screen):
    progress_angle = NumericProperty(0)
    def on_enter(self):
        app = App.get_running_app()
        metrics = app.db.get_latest_metrics()
        if metrics:
            weight, height, goal = metrics
            steps = app.db.get_today_steps()
            dist = FitnessCalculator.calculate_distance(steps, height)
            kcal = FitnessCalculator.calculate_calories(steps, weight)
            self.ids.steps_label.text = str(steps)
            self.ids.goal_label.text = f"из {goal}"
            self.ids.dist_label.text = f"{dist} км"
            self.ids.kcal_label.text = f"{kcal} ккал"
            percent = min(steps / goal, 1.0) if goal > 0 else 0
            self.progress_angle = percent * 360

    def open_settings(self):
        app = App.get_running_app()
        metrics = app.db.get_latest_metrics()
        if metrics: SettingsPopup(current_data=metrics).open()

class ActivityChart(Widget):
    data = ListProperty([])
    labels = ListProperty([])
    mode = StringProperty('week')

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.bind(pos=self.draw_chart, size=self.draw_chart, data=self.draw_chart, mode=self.draw_chart)

    def draw_chart(self, *args):
        self.canvas.clear()
        if not self.data: return

        with self.canvas:
            padding_left, padding_bottom = 60, 50
            chart_width, chart_height = self.width - 80, self.height - 100
            max_val = max(max(self.data), 1000)
            bar_count = len(self.data)
            bar_width = (chart_width / bar_count) * 0.7
            spacing = (chart_width / bar_count) * 0.3
            
            for i, val in enumerate(self.data):
                h = (val / max_val) * chart_height
                x = self.x + padding_left + i * (bar_width + spacing)
                y = self.y + padding_bottom
                
                Color(0.12, 0.58, 0.95, 1)
                RoundedRectangle(pos=(x, y), size=(bar_width, max(h, 2)), radius=[3,])
                

                draw_lbl = False
                if self.mode in ['week', 'year']:
                    draw_lbl = True
                elif self.mode == 'month':
                    day_num = i + 1
                    # Только 1 и числа кратные 5 (5, 10, 15, 20, 25, 30)
                    if day_num == 1 or day_num % 5 == 0:
                        draw_lbl = True

                if draw_lbl:
                    txt = self.labels[i].split('.')[0] if self.mode == 'month' else self.labels[i]
                    lbl = CoreLabel(text=txt, font_size=11)
                    lbl.refresh()
                    Color(0.4, 0.4, 0.4, 1)
                    Rectangle(
                        pos=(x + bar_width/2 - lbl.texture.size[0]/2, y - 25), 
                        size=lbl.texture.size, texture=lbl.texture
                    )

class StatsScreen(Screen):
    current_mode = StringProperty('week')
    offset = NumericProperty(0)

    def on_enter(self):
        self.update_stats()

    def set_mode(self, mode):
        self.current_mode = mode
        self.offset = 0
        self.update_stats()

    def change_offset(self, direction):
        self.offset += direction
        if self.offset < 0: self.offset = 0
        self.update_stats()

    def update_stats(self):
        app = App.get_running_app()
        today = datetime.now()
        
        self.ids.chart.mode = self.current_mode

        if self.current_mode == 'week':
            start = today - timedelta(days=today.weekday()) - timedelta(weeks=self.offset)
            lbls = [(start + timedelta(days=i)).strftime('%d.%m') for i in range(7)]
            d_data, d_lbls = app.db.get_data_for_range(start.strftime('%Y-%m-%d'), (start+timedelta(days=6)).strftime('%Y-%m-%d'))
            final = [d_data[d_lbls.index(l)] if l in d_lbls else 0 for l in lbls]
            self.ids.chart_label.text = f"{lbls[0]} - {lbls[-1]}"
            self.ids.chart.labels, self.ids.chart.data = lbls, final

        elif self.current_mode == 'month':
            m, y = today.month - self.offset, today.year
            while m <= 0: m += 12; y -= 1
            last = calendar.monthrange(y, m)[1]
            lbls = [f"{d:02d}.{m:02d}" for d in range(1, last + 1)]
            d_data, d_lbls = app.db.get_data_for_range(f"{y}-{m:02d}-01", f"{y}-{m:02d}-{last}")
            final = [d_data[d_lbls.index(l)] if l in d_lbls else 0 for l in lbls]
            self.ids.chart_label.text = f"{MONTHS_RU[m]} {y}"
            self.ids.chart.labels, self.ids.chart.data = lbls, final

        elif self.current_mode == 'year':
            y = today.year - self.offset
            data, labels = app.db.get_year_data_for_specific_year(y)
            self.ids.chart_label.text = f"Год {y}"
            self.ids.chart.labels, self.ids.chart.data = labels, data