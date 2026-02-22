import pytest

from utils import calculate_lbm, calculate_target_macros_and_calories


def test_calculate_lbm_for_male_valid():
    lbm = calculate_lbm(weight_kg=80, height_cm=180, gender="male")
    assert lbm == pytest.approx((0.407 * 80) + (0.267 * 180) - 19.2)


def test_calculate_lbm_for_female_valid():
    lbm = calculate_lbm(weight_kg=65, height_cm=170, gender="female")
    assert lbm == pytest.approx((0.252 * 65) + (0.473 * 170) - 48.3)


def test_calculate_lbm_invalid_gender_returns_none():
    assert calculate_lbm(weight_kg=80, height_cm=180, gender="other") is None


def test_calculate_lbm_invalid_data_returns_none():
    assert calculate_lbm(weight_kg=0, height_cm=180, gender="male") is None
    assert calculate_lbm(weight_kg=80, height_cm=0, gender="male") is None
    assert calculate_lbm(weight_kg=80, height_cm=180, gender="") is None


def test_calculate_lbm_unrealistic_returns_none():
    # very low weight + high height creates implausible negative result
    assert calculate_lbm(weight_kg=30, height_cm=220, gender="male") is None


@pytest.mark.parametrize("goal", ["deficit", "maintenance", "surplus"])
def test_calculate_target_macros_and_calories_valid(goal):
    _, calories = calculate_target_macros_and_calories(lbm=60.0, goal=goal)
    assert isinstance(calories, int)
    assert calories > 0


def test_calculate_target_macros_and_calories_invalid_inputs():
    assert calculate_target_macros_and_calories(lbm=0, goal="deficit") is None
    assert calculate_target_macros_and_calories(lbm=60, goal="") is None
    assert calculate_target_macros_and_calories(lbm=60, goal="unknown") is None
