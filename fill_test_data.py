import sqlite3
import random
from datetime import datetime, timedelta
from database import FitnessDB
from calculator import FitnessCalculator

def fill_with_test_data():
    db = FitnessDB()
    # Получаем текущие параметры пользователя для расчета калорий и дистанции
    metrics = db.get_latest_metrics()
    
    if not metrics:
        print("Сначала запустите приложение и настройте профиль!")
        return
    
    weight, height, goal = metrics
    
    # Начинаем с 1 января 2026 года
    start_date = datetime(2026, 1, 1)
    # Заполняем по текущий день (15 марта 2026)
    end_date = datetime(2026, 3, 20)
    
    current_date = start_date
    count = 0

    print("Генерация данных за 2026 год...")

    while current_date <= end_date:
        date_str = current_date.strftime('%Y-%m-%d')
        
        # Генерируем шаги: база 6000 + случайность. 
        # В выходные (5 и 6 индекс) активности меньше
        if current_date.weekday() < 5:
            steps = random.randint(5000, 12000)
        else:
            steps = random.randint(2000, 7000)
            
        dist = FitnessCalculator.calculate_distance(steps, height)
        kcal = FitnessCalculator.calculate_calories(steps, weight)
        
        # Прямая запись в базу данных
        cursor = db.conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO daily_activity (date, steps, distance, calories)
            VALUES (?, ?, ?, ?)
        ''', (date_str, steps, dist, kcal))
        
        current_date += timedelta(days=1)
        count += 1

    db.conn.commit()
    print(f"Готово! Добавлено {count} записей за 2026 год.")

if __name__ == "__main__":
    fill_with_test_data()