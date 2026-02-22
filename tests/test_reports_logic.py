import os
from datetime import date

# Минимальный набор переменных, чтобы импорт модулей проходил в тестовой среде
os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("DB_USER", "test-user")
os.environ.setdefault("DB_PASS", "test-pass")
os.environ.setdefault("DB_HOST", "localhost")
os.environ.setdefault("DB_NAME", "test-db")

from handlers.reports import calculate_average_for_period, calculate_total_norm_for_period


def test_calculate_average_for_period_regular_case():
    assert calculate_average_for_period(14000, 7) == 2000


def test_calculate_average_for_period_zero_days():
    assert calculate_average_for_period(14000, 0) == 0


def test_calculate_total_norm_no_history_with_current_goal():
    total, avg, ok = calculate_total_norm_for_period(
        period_start_date=date(2026, 1, 1),
        period_days=7,
        historical_norms_records=[],
        current_daily_goal=2100,
    )
    assert ok is True
    assert total == 14700
    assert avg == 2100


def test_calculate_total_norm_no_history_no_goal():
    total, avg, ok = calculate_total_norm_for_period(
        period_start_date=date(2026, 1, 1),
        period_days=7,
        historical_norms_records=[],
        current_daily_goal=None,
    )
    assert (total, avg, ok) == (0, 0, False)


def test_calculate_total_norm_from_history_full_period():
    history = [
        {"effective_date": date(2026, 1, 1), "daily_calorie_goal": 2000},
        {"effective_date": date(2026, 1, 4), "daily_calorie_goal": 2200},
    ]
    total, avg, ok = calculate_total_norm_for_period(
        period_start_date=date(2026, 1, 1),
        period_days=7,
        historical_norms_records=history,
        current_daily_goal=2100,
    )
    # days 1-3: 2000, days 4-7: 2200
    assert ok is True
    assert total == (3 * 2000) + (4 * 2200)
    assert avg == round(total / 7)


def test_calculate_total_norm_history_gap_fallback_to_current_goal():
    history = [
        {"effective_date": date(2026, 1, 5), "daily_calorie_goal": 2300},
    ]
    total, avg, ok = calculate_total_norm_for_period(
        period_start_date=date(2026, 1, 1),
        period_days=7,
        historical_norms_records=history,
        current_daily_goal=2100,
    )
    # days 1-4 fallback to current, days 5-7 from history
    assert ok is True
    assert total == (4 * 2100) + (3 * 2300)
    assert avg == round(total / 7)


def test_calculate_total_norm_zero_period_days():
    total, avg, ok = calculate_total_norm_for_period(
        period_start_date=date(2026, 1, 1),
        period_days=0,
        historical_norms_records=[],
        current_daily_goal=2000,
    )
    assert (total, avg, ok) == (0, 0, False)
