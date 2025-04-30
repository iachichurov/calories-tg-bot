import logging
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# Константы для калорийности макронутриентов
CALORIES_PER_GRAM = {
    "protein": 4,
    "fat": 9,
    "carbs": 4
}

# Нормы БЖУ (граммы на кг LBM) для разных целей
MACRO_TARGETS_PER_LBM_KG = {
    "deficit": {"protein": 1.5, "fat": 0.8, "carbs": 2.0},
    "surplus": {"protein": 2.2, "fat": 1.5, "carbs": 4.0},
    "maintenance": { # Среднее между дефицитом и профицитом
        "protein": (1.5 + 2.2) / 2, # 1.85
        "fat": (0.8 + 1.5) / 2,     # 1.15
        "carbs": (2.0 + 4.0) / 2     # 3.0
    }
}

def calculate_lbm(weight_kg: float, height_cm: int, gender: str) -> Optional[float]:
    """
    Рассчитывает сухую массу тела (LBM) по формулам.
    Возвращает LBM в кг или None, если пол не 'male' или 'female'.
    """
    if not weight_kg or not height_cm or not gender:
        return None

    lbm = None
    if gender == 'male':
        # Для мужчин: LBM(кг)=(0.407×W[кг])+(0.267×H[см])−19.2
        lbm = (0.407 * weight_kg) + (0.267 * height_cm) - 19.2
    elif gender == 'female':
        # Для женщин: LBM(кг)=(0.252×W[кг])+(0.473×H[см])−48.3
        lbm = (0.252 * weight_kg) + (0.473 * height_cm) - 48.3
    else:
        logger.warning(f"Неизвестный пол '{gender}' для расчета LBM.")
        return None

    # LBM не может быть отрицательной или больше общего веса (добавим небольшую погрешность)
    if lbm <= 0 or lbm > weight_kg * 1.05:
        logger.warning(f"Неправдоподобный LBM ({lbm:.2f} кг) для W={weight_kg} кг, H={height_cm} см, Пол={gender}. Возвращаем None.")
        return None

    logger.info(f"Расчет LBM: W={weight_kg}, H={height_cm}, Пол={gender} -> LBM={lbm:.2f} кг")
    return lbm

def calculate_target_macros_and_calories(lbm: float, goal: str) -> Optional[Tuple[Dict[str, int], int]]:
    """
    Рассчитывает целевые граммы БЖУ и общую калорийность на основе LBM и цели.
    Возвращает кортеж: (словарь с граммами БЖУ, общая калорийность) или None.
    """
    if not lbm or not goal or goal not in MACRO_TARGETS_PER_LBM_KG:
        logger.warning(f"Некорректные входные данные для расчета макросов: LBM={lbm}, Goal='{goal}'")
        return None

    targets = MACRO_TARGETS_PER_LBM_KG[goal]

    # Рассчитываем граммы БЖУ
    protein_grams = round(targets["protein"] * lbm)
    fat_grams = round(targets["fat"] * lbm)
    carb_grams = round(targets["carbs"] * lbm)

    # Рассчитываем итоговую калорийность
    total_calories = (
        (protein_grams * CALORIES_PER_GRAM["protein"]) +
        (fat_grams * CALORIES_PER_GRAM["fat"]) +
        (carb_grams * CALORIES_PER_GRAM["carbs"])
    )

    macros_grams = {
        "protein": protein_grams,
        "fat": fat_grams,
        "carbs": carb_grams
    }

    logger.info(f"Расчет для LBM={lbm:.2f} кг, Цель='{goal}': БЖУ={macros_grams}, Ккал={total_calories}")
    # Возвращаем словарь с граммами БЖУ и общую калорийность
    # Пока возвращаем только калории, т.к. БЖУ не храним и не показываем
    # return macros_grams, total_calories
    return None, total_calories # Возвращаем None для БЖУ, т.к. они пока не используются

