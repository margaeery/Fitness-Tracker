from kivy.uix.screenmanager import Screen
from kivy.uix.popup import Popup
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.widget import Widget
from kivy.uix.switch import Switch
from kivy.properties import NumericProperty, ListProperty, StringProperty
from kivy.graphics import Color, RoundedRectangle, Rectangle
from kivy.core.text import Label as CoreLabel
from kivy.app import App
from kivy.clock import Clock
from calculator import FitnessCalculator
from datetime import datetime, timedelta
import calendar
import os
import logging

logger = logging.getLogger('FitnessTracker.UI')

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

class SettingsPopup(Popup):
    def __init__(self, current_data, **kwargs):
        super().__init__(**kwargs)
        self.title = "Настройки"
        self.size_hint = (0.9, 0.55)
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

class SetupScreen(Screen):
    def save_profile(self):
        try:
            w = float(self.ids.weight_input.text)
            h = float(self.ids.height_input.text)
            g = int(self.ids.goal_input.text)
            if w <= 0 or h <= 0 or g <= 0: raise ValueError
            app = App.get_running_app()
            app.db.save_user_metrics(w, h, g)
            logger.info(f"Профиль сохранён: weight={w}, height={h}, goal={g}")
            app.restart_with_nav()
        except ValueError:
            logger.warning("Ошибка ввода профиля")
            ErrorPopup(message="Введите корректные числа!").open()

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
            logger.debug(
                f"MainScreen обновлён: steps={steps}, dist={dist}, "
                f"kcal={kcal}, progress={percent:.0%}"
            )

    def open_settings(self):
        app = App.get_running_app()
        metrics = app.db.get_latest_metrics()
        if metrics:
            SettingsPopup(current_data=metrics).open()

class ActivityChart(Widget):
    data = ListProperty([])
    labels = ListProperty([])
    mode = StringProperty('week')
    data_type = StringProperty('steps')  # 'steps', 'distance', 'calories'
    selected_index = NumericProperty(-1)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Перерисовываем при изменении любых свойств
        self.bind(pos=self.draw_chart, size=self.draw_chart, 
                  data=self.draw_chart, mode=self.draw_chart,
                  selected_index=self.draw_chart, data_type=self.draw_chart)

    def on_touch_down(self, touch):
        if self.collide_point(*touch.pos):
            padding_left = 70
            chart_width = self.width - 90
            if not self.data: return False
            
            bar_count = len(self.data)
            total_bar_width = chart_width / bar_count
            
            relative_x = touch.x - (self.x + padding_left)
            index = int(relative_x // total_bar_width)
            
            if 0 <= index < bar_count:
                self.selected_index = index
                return True
        
        self.selected_index = -1
        return super().on_touch_down(touch)

    def draw_chart(self, *args):
        self.canvas.clear()
        if not self.data: return

        with self.canvas:
            padding_left, padding_bottom = 70, 60
            chart_width, chart_height = self.width - 90, self.height - 110
            
            #АДАПТИВНЫЙ РАСЧЕТ МАКСИМУМА
            actual_max = max(self.data) if self.data else 0
            
            if self.data_type == 'steps':
                base, min_limit = 1000, 1000
            elif self.data_type == 'distance':
                base, min_limit = 1, 5
            else:  # calories
                base, min_limit = 100, 500
            
            max_val = max(actual_max, min_limit)
            max_val = ((max_val // base) + 1) * base

            # РИСУЕМ ОСЬ Y И СЕТКУ
            for i in range(5):
                y_val = self.y + padding_bottom + (chart_height / 4) * i
                Color(0.9, 0.9, 0.9, 1)
                Rectangle(pos=(self.x + padding_left, y_val), size=(chart_width, 1))
                
                val_num = (max_val / 4) * i
                # Для дистанции показываем 1 знак после запятой
                step_label = f"{val_num:.1f}" if self.data_type == 'distance' else str(int(val_num))
                
                lbl = CoreLabel(text=step_label, font_size=20)
                lbl.refresh()
                Color(0.4, 0.4, 0.4, 1)
                Rectangle(
                    pos=(self.x + 10, y_val - lbl.texture.size[1]/2),
                    size=lbl.texture.size, texture=lbl.texture
                )

            # РИСУЕМ СТОЛБИКИ
            bar_count = len(self.data)
            bar_width = (chart_width / bar_count) * 0.7
            spacing = (chart_width / bar_count) * 0.3
            
            selected_info = None

            for i, val in enumerate(self.data):
                h = (val / max_val) * chart_height if max_val > 0 else 0
                x = self.x + padding_left + i * (bar_width + spacing)
                y = self.y + padding_bottom
                
                if i == self.selected_index:
                    Color(0.95, 0.3, 0.3, 1)
                    selected_info = (x, y, h, val)
                else:
                    Color(0.12, 0.58, 0.95, 1)
                
                RoundedRectangle(pos=(x, y), size=(bar_width, max(h, 2)), radius=[3,])
                
                # Подписи оси X
                draw_lbl = False
                if self.mode in ['week', 'year']:
                    draw_lbl = True
                elif self.mode == 'month' and (i == 0 or (i + 1) % 5 == 0):
                    draw_lbl = True

                if draw_lbl:
                    txt = self.labels[i].split('.')[0] if self.mode == 'month' else self.labels[i]
                    lbl_x = CoreLabel(text=txt, font_size=20)
                    lbl_x.refresh()
                    Color(0.4, 0.4, 0.4, 1)
                    Rectangle(
                        pos=(x + bar_width/2 - lbl_x.texture.size[0]/2, y - 25), 
                        size=lbl_x.texture.size, texture=lbl_x.texture
                    )

            # РИСУЕМ ПОДСКАЗКУ
            if selected_info:
                sx, sy, sh, sval = selected_info
                tip_text = f"{sval:.2f}" if self.data_type == 'distance' else str(int(sval))
                tip_lbl = CoreLabel(text=tip_text, font_size=20, bold=True)
                tip_lbl.refresh()
                
                tw, th = tip_lbl.texture.size[0] + 12, tip_lbl.texture.size[1] + 8
                tx, ty = sx + bar_width/2 - tw/2, sy + sh + 8

                Color(0.1, 0.1, 0.1, 1)
                Rectangle(pos=(tx, ty), size=(tw, th))
                Color(1, 1, 1, 1)
                Rectangle(pos=(tx + 6, ty + 4), size=tip_lbl.texture.size, texture=tip_lbl.texture)


class StatsScreen(Screen):
    current_mode = StringProperty('week')
    data_type = StringProperty('steps')
    offset = NumericProperty(0)

    def on_enter(self):
        self.update_stats()

    def set_mode(self, mode):
        self.current_mode = mode
        self.offset = 0
        self.update_stats()

    def set_data_type(self, dtype):
        self.data_type = dtype
        self.update_stats()

    def change_offset(self, direction):
        self.offset += direction
        if self.offset < 0: self.offset = 0
        self.update_stats()

    def update_stats(self):
        app = App.get_running_app()
        today = datetime.now()
        
        # Синхронизируем свойства виджета графика
        self.ids.chart.mode = self.current_mode
        self.ids.chart.data_type = self.data_type

        logger.debug(
            f"StatsScreen.update_stats: mode={self.current_mode}, "
            f"type={self.data_type}, offset={self.offset}"
        )
        
        if self.current_mode == 'week':
            start = today - timedelta(days=today.weekday()) - timedelta(weeks=self.offset)
            lbls = [(start + timedelta(days=i)).strftime('%d.%m') for i in range(7)]
            
            d_lbls, d_dict = app.db.get_data_for_range(
                start.strftime('%Y-%m-%d'), 
                (start + timedelta(days=6)).strftime('%Y-%m-%d')
            )
            
            raw_data = d_dict[self.data_type]
            final = [raw_data[d_lbls.index(l)] if l in d_lbls else 0 for l in lbls]
            
            # Формат заголовка: "день.месяц - день.месяц год"
            year_str = start.strftime('%Y')
            self.ids.chart_label.text = f"{lbls[0]} - {lbls[-1]} {year_str}"
            self.ids.chart.labels, self.ids.chart.data = lbls, final

        elif self.current_mode == 'month':
            m, y = today.month - self.offset, today.year
            while m <= 0: m += 12; y -= 1
            last = calendar.monthrange(y, m)[1]
            lbls = [f"{d:02d}.{m:02d}" for d in range(1, last + 1)]
            
            d_lbls, d_dict = app.db.get_data_for_range(f"{y}-{m:02d}-01", f"{y}-{m:02d}-{last}")
            raw_data = d_dict[self.data_type]
            final = [raw_data[d_lbls.index(l)] if l in d_lbls else 0 for l in lbls]
            
            self.ids.chart_label.text = f"{MONTHS_RU[m]} {y}"
            self.ids.chart.labels, self.ids.chart.data = lbls, final

        elif self.current_mode == 'year':
            y = today.year - self.offset
            labels, res_data = app.db.get_year_data_for_specific_year(y)
            final_data = res_data[self.data_type]
            
            self.ids.chart_label.text = f"{y}" 
            self.ids.chart.labels, self.ids.chart.data = labels, final_data

