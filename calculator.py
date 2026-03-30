class FitnessCalculator:
    @staticmethod
    def calculate_distance(steps, height):
        # Средняя длина шага = рост * 0.414 (в метрах)
        step_length = (height / 100) * 0.414
        distance_km = (steps * step_length) / 1000
        return round(distance_km, 2)

    @staticmethod
    def calculate_calories(steps, weight):
        # Упрощенная формула: 0.5 ккал на кг веса за 1000 шагов
        # Или: вес * 0.0005 * шаги
        calories = steps * weight * 0.0005
        return round(calories, 1)