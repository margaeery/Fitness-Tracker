import sqlite3
import logging
from datetime import datetime
import os

logger = logging.getLogger('FitnessTracker.Database')

# Путь к данным приложения (работает на Android и desktop)
try:
    from android.storage import app_storage_path
    DB_PATH = app_storage_path()
except ImportError:
    DB_PATH = os.path.dirname(os.path.abspath(__file__))

class FitnessDB:
    def __init__(self, db_name="fitness_data.db"):
        # При инициализации создаем соединение и таблицы
        db_full_path = os.path.join(DB_PATH, db_name)
        os.makedirs(DB_PATH, exist_ok=True)
        self.conn = sqlite3.connect(db_full_path, isolation_level=None)
        logger.info(f"БД открыта: {db_full_path}")
        self.create_tables()

    def create_tables(self):
        cursor = self.conn.cursor()

        # Таблица активности
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS daily_activity (
                date TEXT PRIMARY KEY,
                steps INTEGER DEFAULT 0,
                distance REAL DEFAULT 0.0,
                calories REAL DEFAULT 0.0
            )
        ''')

        # Таблица метрик пользователя
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_metrics (
                date TEXT PRIMARY KEY,
                weight REAL,
                height REAL,
                step_goal INTEGER
            )
        ''')

        # Таблица состояния датчика шагов (baseline за каждый день)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS sensor_state (
                date TEXT PRIMARY KEY,
                baseline INTEGER NOT NULL
            )
        ''')

        self.conn.commit()
        logger.debug("Таблицы БД проверены / созданы")


    def save_user_metrics(self, weight, height, goal):
        """Сохраняет или обновляет параметры пользователя на текущую дату"""
        today = datetime.now().strftime('%Y-%m-%d')
        cursor = self.conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO user_metrics (date, weight, height, step_goal)
            VALUES (?, ?, ?, ?)
        ''', (today, weight, height, goal))
        self.conn.commit()
        logger.info(f"Метрики сохранены: weight={weight}, height={height}, goal={goal}")

    def get_latest_metrics(self):
        """Возвращает последние введенные параметры пользователя"""
        cursor = self.conn.cursor()
        cursor.execute('SELECT weight, height, step_goal FROM user_metrics ORDER BY date DESC LIMIT 1')
        res = cursor.fetchone()
        return res if res else None


    def add_steps(self, steps_to_add):
        """Добавляет шаги к текущему дню"""
        today = datetime.now().strftime('%Y-%m-%d')
        cursor = self.conn.cursor()
        
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
    

    def get_data_for_range(self, start_date, end_date):
        """Возвращает метки дат и словари данных для диапазона"""
        cursor = self.conn.cursor()
        # Извлекаем все нужные поля
        cursor.execute('''
            SELECT strftime('%d.%m', date), steps, distance, calories 
            FROM daily_activity 
            WHERE date >= ? AND date <= ? ORDER BY date ASC
        ''', (start_date, end_date))
        rows = cursor.fetchall()
        
        if not rows:
            return [], {'steps': [], 'distance': [], 'calories': []}
        
        labels = [r[0] for r in rows]
        data = {
            'steps': [r[1] for r in rows],
            'distance': [r[2] for r in rows],
            'calories': [r[3] for r in rows]
        }
        return labels, data

    def get_year_data_for_specific_year(self, year):
        """Возвращает суммы по месяцам для года"""
        cursor = self.conn.cursor()
        labels = ["Янв", "Фев", "Мар", "Апр", "Май", "Июн", "Июл", "Авг", "Сен", "Окт", "Ноя", "Дек"]
        res_data = {'steps': [], 'distance': [], 'calories': []}
        
        for i in range(1, 13):
            month_str = f"{i:02d}"
            cursor.execute('''
                SELECT SUM(steps), SUM(distance), SUM(calories) 
                FROM daily_activity 
                WHERE strftime('%m', date) = ? AND strftime('%Y', date) = ?
            ''', (month_str, str(year)))
            res = cursor.fetchone()
            res_data['steps'].append(res[0] if res[0] else 0)
            res_data['distance'].append(res[1] if res[1] else 0)
            res_data['calories'].append(res[2] if res[2] else 0)
            
        return labels, res_data

    # Методы для датчика шагов

    def get_sensor_baseline(self, date):
        """Возвращает baseline датчика для указанной даты или None."""
        cursor = self.conn.cursor()
        cursor.execute(
            'SELECT baseline FROM sensor_state WHERE date = ?', (date,)
        )
        row = cursor.fetchone()
        return row[0] if row else None

    def save_sensor_baseline(self, date, baseline):
        """Сохраняет или обновляет baseline датчика для указанной даты."""
        cursor = self.conn.cursor()
        cursor.execute(
            'INSERT OR REPLACE INTO sensor_state (date, baseline) VALUES (?, ?)',
            (date, baseline),
        )
        self.conn.commit()
        logger.debug(f"Baseline сохранён: date={date}, baseline={baseline}")

    def delete_sensor_baseline(self, date):
        """Удаляет baseline датчика для указанной даты (сервис пересчитает)."""
        cursor = self.conn.cursor()
        cursor.execute('DELETE FROM sensor_state WHERE date = ?', (date,))
        self.conn.commit()
        logger.debug(f"Baseline удалён: date={date}")

    def update_day_activity(self, date, steps, distance, calories):
        """Обновляет все поля активности за указанный день (абсолютные значения)."""
        cursor = self.conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO daily_activity (date, steps, distance, calories)
            VALUES (?, ?, ?, ?)
        ''', (date, steps, distance, calories))
        self.conn.commit()

    def get_activity_for_date(self, date_str):
        """Возвращает (steps, distance, calories) для указанной даты."""
        cursor = self.conn.cursor()
        cursor.execute(
            'SELECT steps, distance, calories FROM daily_activity WHERE date = ?',
            (date_str,)
        )
        row = cursor.fetchone()
        return (row[0], row[1], row[2]) if row else (0, 0.0, 0.0)

    def close(self):
        """Закрыть соединение с базой"""
        logger.info("БД закрыта")
        self.conn.close()