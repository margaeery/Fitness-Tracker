class FitnessCalculator:
    @staticmethod
    def calculate_distance(steps, height):
        step_length = (height / 100 / 4) + 0.37
        distance_km = (steps * step_length) / 1000
        return round(distance_km, 2)

    @staticmethod
    def calculate_calories(steps, weight):
        """
        На основе данных: Ходьба (110 ш/мин) = 0.0680, Сон = 0.0155 ккал/мин/кг.
        Коэффициент: (0.0680 - 0.0155) / 110 = 0.000477
        """
        calories_per_step_per_kg = 0.000477
        calories = steps * weight * calories_per_step_per_kg       
        return round(calories, 1)