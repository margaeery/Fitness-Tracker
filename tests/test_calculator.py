"""Модульные тесты: FitnessCalculator."""

import pytest
from calculator import FitnessCalculator


class TestCalculateDistance:
    """Тесты FitnessCalculator.calculate_distance."""

    def test_zero_steps(self):
        assert FitnessCalculator.calculate_distance(0, 175.0) == 0.0

    def test_positive_steps(self):
        dist = FitnessCalculator.calculate_distance(1000, 175.0)
        # step_length = 175/100/4 + 0.37 = 0.8075
        # distance = 1000 * 0.8075 / 1000 = 0.8075 → 0.81
        assert dist == 0.81

    def test_different_heights(self):
        d150 = FitnessCalculator.calculate_distance(1000, 150.0)
        d190 = FitnessCalculator.calculate_distance(1000, 190.0)
        # Более высокий человек → длиннее шаг → больше дистанция
        assert d190 > d150

    def test_large_step_count(self):
        dist = FitnessCalculator.calculate_distance(20000, 175.0)
        assert dist > 0
        assert isinstance(dist, float)

    def test_result_rounded(self):
        dist = FitnessCalculator.calculate_distance(1234, 168.0)
        # Проверяем, что ровно 2 знака после запятой
        assert dist == round(dist, 2)


class TestCalculateCalories:
    """Тесты FitnessCalculator.calculate_calories."""

    def test_zero_steps(self):
        assert FitnessCalculator.calculate_calories(0, 70.0) == 0.0

    def test_positive_steps(self):
        kcal = FitnessCalculator.calculate_calories(1000, 70.0)
        # 1000 * 70 * 0.000477 = 33.39 → 33.4
        assert kcal == 33.4

    def test_heavier_person_burns_more(self):
        k_light = FitnessCalculator.calculate_calories(5000, 50.0)
        k_heavy = FitnessCalculator.calculate_calories(5000, 100.0)
        assert k_heavy > k_light

    def test_more_steps_more_calories(self):
        k1 = FitnessCalculator.calculate_calories(1000, 70.0)
        k2 = FitnessCalculator.calculate_calories(5000, 70.0)
        assert k2 > k1

    def test_result_rounded(self):
        kcal = FitnessCalculator.calculate_calories(7777, 83.5)
        assert kcal == round(kcal, 1)

    def test_proportional(self):
        """Калории линейно зависят от шагов."""
        k1 = FitnessCalculator.calculate_calories(1000, 70.0)
        k2 = FitnessCalculator.calculate_calories(2000, 70.0)
        assert abs(k2 - 2 * k1) < 0.2  # допуск на округление
