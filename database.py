import sqlite3
from datetime import datetime

class FitnessDB:
    def __init__(self, db_name="fitness_data.db"):
        # При инициализации создаем соединение и таблицы
        self.conn = sqlite3.connect(db_name)
        self.create_tables()

    def create_tables(self):
        cursor = self.conn.cursor()
        
        # 1. Таблица активности (шаги за каждый день)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS daily_activity (
                date TEXT PRIMARY KEY,
                steps INTEGER DEFAULT 0,
                distance REAL DEFAULT 0.0,
                calories REAL DEFAULT 0.0
            )
        ''')
        
        # 2. Таблица метрик пользователя (параметры тела и цели)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_metrics (
                date TEXT PRIMARY KEY,
                weight REAL,
                height REAL,
                step_goal INTEGER
            )
        ''')
        self.conn.commit()

    # --- Методы для работы с профилем пользователя ---

    def save_user_metrics(self, weight, height, goal):
        """Сохраняет или обновляет параметры пользователя на текущую дату"""
        today = datetime.now().strftime('%Y-%m-%d')
        cursor = self.conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO user_metrics (date, weight, height, step_goal)
            VALUES (?, ?, ?, ?)
        ''', (today, weight, height, goal))
        self.conn.commit()

    def get_latest_metrics(self):
        """Возвращает последние введенные параметры пользователя"""
        cursor = self.conn.cursor()
        cursor.execute('SELECT weight, height, step_goal FROM user_metrics ORDER BY date DESC LIMIT 1')
        res = cursor.fetchone()
        return res if res else None

    # --- Методы для работы с шагами ---

    def add_steps(self, steps_to_add):
        """Добавляет шаги к текущему дню"""
        today = datetime.now().strftime('%Y-%m-%d')
        cursor = self.conn.cursor()
        
        # Проверяем, есть ли запись за сегодня
        cursor.execute('SELECT steps FROM daily_activity WHERE date = ?', (today,))
        res = cursor.fetchone()
        
        if res:
            new_steps = res[0] + steps_to_add
            cursor.execute('UPDATE daily_activity SET steps = ? WHERE date = ?', (new_steps, today))
        else:
            cursor.execute('INSERT INTO daily_activity (date, steps) VALUES (?, ?)', (today, steps_to_add))
        
        self.conn.commit()

    def get_today_steps(self):
        """Возвращает количество шагов за текущую дату"""
        cursor = self.conn.cursor()
        today = datetime.now().strftime('%Y-%m-%d')
        cursor.execute('SELECT steps FROM daily_activity WHERE date = ?', (today,))
        res = cursor.fetchone()
        return res[0] if res else 0
    
    # --- Методы для статистики и графиков ---

    def get_data_for_range(self, start_date, end_date):
        """Возвращает данные и метки (дни) для диапазона дат"""
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT strftime('%d.%m', date), steps FROM daily_activity 
            WHERE date >= ? AND date <= ? ORDER BY date ASC
        ''', (start_date, end_date))
        rows = cursor.fetchall()
        
        # Возвращаем два списка: [шаги], [метки_дат]
        if not rows:
            return [], []
        return [r[1] for r in rows], [r[0] for r in rows]

    def get_year_data_for_specific_year(self, year):
        """Возвращает суммы шагов по месяцам для конкретного года"""
        cursor = self.conn.cursor()
        steps = []
        # Сокращенные названия месяцев для графика
        labels = ["Янв", "Фев", "Мар", "Апр", "Май", "Июн", "Июл", "Авг", "Сен", "Окт", "Ноя", "Дек"]
        
        for i in range(1, 13):
            month_str = f"{i:02d}"
            cursor.execute('''
                SELECT SUM(steps) FROM daily_activity 
                WHERE strftime('%m', date) = ? AND strftime('%Y', date) = ?
            ''', (month_str, str(year)))
            res = cursor.fetchone()[0]
            steps.append(res if res else 0)
            
        return steps, labels

    def close(self):
        """Закрыть соединение с базой"""
        self.conn.close()