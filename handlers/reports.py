import logging
# Импортируем необходимые модули для работы с датой/временем и часовыми поясами
from datetime import datetime, time, date, timedelta
import pytz
# defaultdict удобен для группировки по дням
from collections import defaultdict
# escape для безопасного вывода текста в HTML-разметке
from html import escape
# Импорты aiogram для роутера, фильтров и типов
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

# Импортируем наши модули: функции БД и клавиатуры
import database as db
from keyboards import main_action_keyboard
# utils нам здесь не нужен, т.к. норма уже рассчитана и хранится в БД

# Настраиваем логирование для этого модуля
logger = logging.getLogger(__name__)


# Критический расчётный функционал (вынесен для юнит-тестов)
def calculate_average_for_period(total_value: int, period_days: int) -> int:
    """Возвращает среднее значение за полный период (округление до int)."""
    if period_days <= 0:
        return 0
    return round(total_value / period_days)


def calculate_total_norm_for_period(
    period_start_date: date,
    period_days: int,
    historical_norms_records: list[dict],
    current_daily_goal: int | None,
) -> tuple[int, int, bool]:
    """
    Рассчитывает суммарную и среднюю норму за полный период.

    Возвращает: (total_norm_period, average_norm_period, norm_calculated)
    """
    if period_days <= 0:
        return 0, 0, False

    if not historical_norms_records:
        if current_daily_goal:
            total_norm_period = current_daily_goal * period_days
            return total_norm_period, current_daily_goal, True
        return 0, 0, False

    norms_dict = {
        record['effective_date']: record['daily_calorie_goal']
        for record in historical_norms_records
    }
    history_dates_sorted = sorted(norms_dict.keys())

    total_norm_period = 0
    applicable_norm_found_for_any_day = False

    for i in range(period_days):
        entry_date = period_start_date + timedelta(days=i)
        applicable_norm = None
        for history_date in reversed(history_dates_sorted):
            if history_date <= entry_date:
                applicable_norm = norms_dict[history_date]
                break

        if applicable_norm is not None:
            total_norm_period += applicable_norm
            applicable_norm_found_for_any_day = True
        elif current_daily_goal:
            total_norm_period += current_daily_goal
            applicable_norm_found_for_any_day = True

    if not applicable_norm_found_for_any_day:
        return 0, 0, False

    return total_norm_period, round(total_norm_period / period_days), True


# Словарь с русскими названиями месяцев для красивого вывода
RUSSIAN_MONTHS = {
    1: "Январь", 2: "Февраль", 3: "Март", 4: "Апрель",
    5: "Май", 6: "Июнь", 7: "Июль", 8: "Август",
    9: "Сентябрь", 10: "Октябрь", 11: "Ноябрь", 12: "Декабрь"
}

# Создаем роутер для команд отчетов (/today, /week, /month)
router = Router()

@router.message(Command("today"))
async def handle_today(message: Message):
    """Обработчик команды /today. Показывает сводку, норму и мотивацию."""
    user_id = message.from_user.id
    logger.info(f"Пользователь {user_id} запросил сводку за сегодня.")

    # Проверяем наличие пула соединений с БД
    if not db.db_pool:
        logger.warning("Пул соединений с БД не инициализирован при обработке /today.")
        await message.answer(
            "Возникла проблема с подключением к базе данных. Попробуйте позже."
        )
        return

    # --- Получаем часовой пояс и данные профиля пользователя ---
    tz_name = await db.get_user_timezone(db.db_pool, user_id)
    profile_data = await db.get_user_profile_data(db.db_pool, user_id) # Получаем профиль

    try:
        # Пытаемся создать объект часового пояса
        user_tz = pytz.timezone(tz_name)
    except pytz.UnknownTimeZoneError:
        # Если пояс некорректный, используем UTC и логируем предупреждение
        logger.warning(
            f"Некорректный часовой пояс '{tz_name}' для {user_id} в /today. "
            f"Используется UTC."
        )
        user_tz = pytz.utc # Используем UTC как fallback

    # Получаем записи о еде за сегодня с учетом часового пояса
    entries = await db.get_todays_food_entries(db.db_pool, user_id, tz_name)

    # Считаем общую калорийность потребленную за сегодня
    total_calories_consumed = sum(entry['calories_consumed'] for entry in entries)

    # Формируем список продуктов
    entries_text_parts = []
    if entries:
        for i, entry in enumerate(entries):
            try:
                product_name = entry['product_name']
                weight = entry['weight_grams']
                calories = entry['calories_consumed']

                product_name_safe = escape(product_name) # Экранируем для HTML
                formatted_string = (
                    f"- {product_name_safe} ({weight}г): {calories} ккал"
                )
                entries_text_parts.append(formatted_string)
            except KeyError as e:
                logger.error(
                    f"Ошибка KeyError при доступе к полю записи {i+1}: {e}. "
                    f"Данные записи: {dict(entry)}"
                )
            except Exception as e:
                 logger.error(
                     f"Неожиданная ошибка при обработке записи {i+1}: {e}. "
                     f"Данные записи: {dict(entry)}", exc_info=True
                 )

        entries_text = "\n".join(entries_text_parts)
    else:
        entries_text = "Пока ничего не добавлено."

    # --- Формируем блок с нормой и мотивацией ---
    goal_section = ""
    motivation_message = ""

    if profile_data:
        daily_goal_calories = profile_data.get('daily_calorie_goal')
        user_goal = profile_data.get('goal')

        if daily_goal_calories: # Если норма рассчитана
            goal_section = f"🎯 Ваша дневная норма: ~<b>{daily_goal_calories}</b> ккал\n"
            # Формируем мотивацию, если есть цель и норма
            if user_goal:
                diff = total_calories_consumed - daily_goal_calories
                if user_goal == 'deficit':
                    if diff <= 0:
                        motivation_message = "👍 Ты молодец! Продолжай в том же духе."
                    else:
                        motivation_message = (
                            f"⚠️ Превышение нормы на {diff} ккал. "
                            f"Не сдавайся, у тебя получится!"
                        )
                elif user_goal == 'maintenance':
                    if abs(diff) < daily_goal_calories * 0.05: # +/- 5%
                        motivation_message = "✅ Отлично! Норма калорий соблюдена."
                    elif diff > 0:
                        motivation_message = f"📈 Небольшое превышение нормы (+{diff} ккал)."
                    else:
                        motivation_message = f"📉 Немного не добрали до нормы ({diff} ккал)."
                elif user_goal == 'surplus':
                    if diff >= 0:
                        motivation_message = "💪 Отличная работа! Вы в профиците."
                    else:
                        motivation_message = f"⏳ Нужно еще {-diff} ккал для достижения профицита."
        else:
             goal_section = "🎯 Дневная норма не рассчитана. Заполните профиль в /settings.\n"
    else:
        goal_section = "🎯 Дневная норма не рассчитана. Заполните профиль в /settings.\n"

    # --- Собираем итоговое сообщение ---
    now_local_str = datetime.now(user_tz).strftime('%d.%m.%Y')
    final_message_parts = [
        f"📊 <b>Сводка за сегодня ({now_local_str}, {tz_name}):</b>\n",
        goal_section
    ]
    if motivation_message:
        final_message_parts.append(f"<i>{motivation_message}</i>\n")

    final_message_parts.extend([
        f"--------------------\n",
        f"Потреблено сегодня: <b>{total_calories_consumed}</b> ккал\n",
        entries_text
    ])

    # Отправляем собранное сообщение
    await message.answer(
        "\n".join(part for part in final_message_parts if part),
        reply_markup=main_action_keyboard()
    )


# --- Отчет за неделю (с исторической нормой) ---
@router.message(Command("week"))
async def handle_week(message: Message):
    """Обработчик команды /week. Показывает отчет за последние 7 дней с исторической нормой."""
    user_id = message.from_user.id
    logger.info(f"Пользователь {user_id} запросил отчет за неделю.")

    if not db.db_pool:
        logger.warning("Пул БД не инициализирован для /week.")
        await message.answer("Проблема с БД.")
        return

    # Получаем пояс и текущий профиль
    tz_name = await db.get_user_timezone(db.db_pool, user_id)
    profile_data = await db.get_user_profile_data(db.db_pool, user_id)
    current_daily_goal = profile_data.get('daily_calorie_goal') if profile_data else None

    try:
        user_tz = pytz.timezone(tz_name)
    except pytz.UnknownTimeZoneError:
        logger.warning(
            f"Некорректный TZ '{tz_name}' для {user_id} в /week. Используется UTC."
        )
        user_tz = pytz.utc

    # Получаем записи о еде за период
    num_days_report = 7
    entries = await db.get_last_n_days_entries(
        db.db_pool, user_id, tz_name, days=num_days_report
    )

    if not entries:
        await message.answer(
            f"📅 За последние {num_days_report} дней записей не найдено.",
            reply_markup=main_action_keyboard()
        )
        return

    # Группируем потребление по локальным датам
    calories_by_day = defaultdict(int)
    for entry in entries:
        entry_local_time = entry['entry_timestamp'].astimezone(user_tz)
        entry_date = entry_local_time.date()
        calories_by_day[entry_date] += entry['calories_consumed']

    total_calories_consumed = sum(calories_by_day.values())
    average_calories_consumed = calculate_average_for_period(total_calories_consumed, num_days_report)

    # --- Расчет исторической нормы ---
    # Определяем границы периода
    report_end_date = datetime.now(user_tz).date()
    report_start_date = report_end_date - timedelta(days=num_days_report - 1)

    # Получаем историю
    historical_norms_records = await db.get_historical_norms(
        db.db_pool, user_id, report_start_date, report_end_date
    )

    total_norm_period, average_norm_period, norm_calculated = calculate_total_norm_for_period(
        period_start_date=report_start_date,
        period_days=num_days_report,
        historical_norms_records=historical_norms_records,
        current_daily_goal=current_daily_goal,
    )

    # --- Формируем текст отчета ---
    report_parts = [f"📅 <b>Отчет за последние {num_days_report} дней ({tz_name}):</b>\n"]
    report_parts.append("По дням (потреблено):")
    for i in range(num_days_report):
        current_date = report_end_date - timedelta(days=i)
        cals_consumed = calories_by_day.get(current_date, 0)
        report_parts.append(f"- {current_date.strftime('%d.%m')}: {cals_consumed} ккал")

    report_parts.append(f"\n--------------------")
    if norm_calculated:
        report_parts.append(
            f"Потреблено всего: <b>{total_calories_consumed}</b> ккал "
            f"(при норме ~{total_norm_period} ккал)"
        )
        report_parts.append(
            f"Среднесуточное: <b>{average_calories_consumed}</b> ккал "
            f"(при норме ~{average_norm_period} ккал)"
        )
    else:
        report_parts.append(f"Потреблено всего: <b>{total_calories_consumed}</b> ккал")
        report_parts.append(
            f"Среднесуточное: <b>{average_calories_consumed}</b> ккал "
            f"(за {num_days_report} дн.)"
        )
        report_parts.append(
            f"<i>(Норма не рассчитана. Заполните профиль в /settings)</i>"
        )

    # Отправляем отчет
    await message.answer("\n".join(report_parts), reply_markup=main_action_keyboard())


# --- Отчет за месяц (с исторической нормой) ---
@router.message(Command("month"))
async def handle_month(message: Message):
    """Обработчик команды /month. Показывает отчет за текущий месяц с исторической нормой."""
    user_id = message.from_user.id
    logger.info(f"Пользователь {user_id} запросил отчет за месяц.")

    if not db.db_pool:
        logger.warning("Пул БД не инициализирован для /month.")
        await message.answer("Проблема с БД.")
        return

    # Получаем пояс и текущий профиль
    tz_name = await db.get_user_timezone(db.db_pool, user_id)
    profile_data = await db.get_user_profile_data(db.db_pool, user_id)
    current_daily_goal = profile_data.get('daily_calorie_goal') if profile_data else None

    try:
        user_tz = pytz.timezone(tz_name)
    except pytz.UnknownTimeZoneError:
        logger.warning(
            f"Некорректный TZ '{tz_name}' для {user_id} в /month. Используется UTC."
        )
        user_tz = pytz.utc

    # Получаем записи о еде за месяц
    entries = await db.get_current_month_entries(db.db_pool, user_id, tz_name)

    if not entries:
        await message.answer(
            f"🗓️ За текущий месяц записей пока нет.",
            reply_markup=main_action_keyboard()
        )
        return

    # Группируем потребление по дням
    calories_by_day = defaultdict(int)
    for entry in entries:
        entry_local_time = entry['entry_timestamp'].astimezone(user_tz)
        entry_date = entry_local_time.date()
        calories_by_day[entry_date] += entry['calories_consumed']

    total_calories_consumed = sum(calories_by_day.values())

    # Определяем границы месяца
    now_local = datetime.now(user_tz)
    report_start_date = date(now_local.year, now_local.month, 1)
    report_end_date = now_local.date() # Конец - сегодняшний день
    days_in_period = now_local.day
    average_calories_consumed = calculate_average_for_period(total_calories_consumed, days_in_period)

    # --- Расчет исторической нормы ---
    # Получаем историю
    historical_norms_records = await db.get_historical_norms(
        db.db_pool, user_id, report_start_date, report_end_date
    )

    total_norm_period, average_norm_period, norm_calculated = calculate_total_norm_for_period(
        period_start_date=report_start_date,
        period_days=days_in_period,
        historical_norms_records=historical_norms_records,
        current_daily_goal=current_daily_goal,
    )

    # --- Формируем текст отчета ---
    month_number = now_local.month
    month_name = RUSSIAN_MONTHS.get(month_number, f"Месяц {month_number}")
    report_parts = [f"🗓️ <b>Отчет за {month_name} {now_local.year} ({tz_name}):</b>\n"]
    report_parts.append(f"--------------------")
    if norm_calculated:
        report_parts.append(
            f"Потреблено всего: <b>{total_calories_consumed}</b> ккал "
            f"(при норме ~{total_norm_period} ккал)"
        )
        report_parts.append(
            f"Среднесуточное: <b>{average_calories_consumed}</b> ккал "
            f"(при норме ~{average_norm_period} ккал)"
        )
    else:
        report_parts.append(f"Потреблено всего: <b>{total_calories_consumed}</b> ккал")
        report_parts.append(
            f"Среднесуточное: <b>{average_calories_consumed}</b> ккал "
            f"(за {days_in_period} дн.)"
        )
        report_parts.append(
            f"<i>(Норма не рассчитана. Заполните профиль в /settings)</i>"
        )

    # Отправляем отчет
    await message.answer("\n".join(report_parts), reply_markup=main_action_keyboard())
