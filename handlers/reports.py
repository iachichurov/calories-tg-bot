import logging
# Импортируем нужные модули
from datetime import datetime, time, date, timedelta
import pytz
from collections import defaultdict
from html import escape
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

# Импортируем функции БД и клавиатуры
import database as db
from keyboards import main_action_keyboard

# Настраиваем логирование
logger = logging.getLogger(__name__)

# Словарь с русскими названиями месяцев
RUSSIAN_MONTHS = {
    1: "Январь", 2: "Февраль", 3: "Март", 4: "Апрель",
    5: "Май", 6: "Июнь", 7: "Июль", 8: "Август",
    9: "Сентябрь", 10: "Октябрь", 11: "Ноябрь", 12: "Декабрь"
}

# Создаем роутер
router = Router()

@router.message(Command("today"))
async def handle_today(message: Message):
    """Обработчик команды /today. Показывает сводку, норму и мотивацию."""
    user_id = message.from_user.id
    logger.info(f"Пользователь {user_id} запросил сводку за сегодня.")

    if not db.db_pool:
        logger.warning("Пул соединений с БД не инициализирован при обработке /today.")
        await message.answer("Возникла проблема с подключением к базе данных. Попробуйте позже.")
        return

    # Получаем часовой пояс и данные профиля
    tz_name = await db.get_user_timezone(db.db_pool, user_id)
    profile_data = await db.get_user_profile_data(db.db_pool, user_id)

    try: user_tz = pytz.timezone(tz_name)
    except pytz.UnknownTimeZoneError: logger.warning(f"Некорректный TZ '{tz_name}' для {user_id}. Используется UTC."); user_tz = pytz.utc

    # Получаем записи за сегодня
    entries = await db.get_todays_food_entries(db.db_pool, user_id, tz_name)

    # Считаем потребленные калории
    total_calories_consumed = sum(entry['calories_consumed'] for entry in entries)

    # Формируем список продуктов
    entries_text_parts = []
    if entries:
        for entry in entries:
            product_name_safe = escape(entry['product_name'])
            entries_text_parts.append(f"- {product_name_safe} ({entry['weight_grams']}г): {entry['calories_consumed']} ккал")
        entries_text = "\n".join(entries_text_parts)
    else:
        entries_text = "Пока ничего не добавлено."

    # Формируем блок с нормой и мотивацией
    goal_section = ""; motivation_message = ""; daily_goal_calories = None
    if profile_data:
        daily_goal_calories = profile_data.get('daily_calorie_goal')
        user_goal = profile_data.get('goal')
        if daily_goal_calories:
            goal_section = f"🎯 Ваша дневная норма: ~<b>{daily_goal_calories}</b> ккал\n"
            if user_goal:
                diff = total_calories_consumed - daily_goal_calories
                if user_goal == 'deficit': motivation_message = "👍 Ты молодец! Продолжай в том же духе." if diff <= 0 else f"⚠️ Превышение нормы на {diff} ккал. Не сдавайся, у тебя получится!"
                elif user_goal == 'maintenance': motivation_message = "✅ Отлично! Норма калорий соблюдена." if abs(diff) < daily_goal_calories * 0.05 else (f"📈 Небольшое превышение нормы (+{diff} ккал)." if diff > 0 else f"📉 Немного не добрали до нормы ({diff} ккал).")
                elif user_goal == 'surplus': motivation_message = "💪 Отличная работа! Вы в профиците." if diff >= 0 else f"⏳ Нужно еще {-diff} ккал для достижения профицита."
        else: goal_section = "🎯 Дневная норма не рассчитана. Заполните профиль в /settings.\n"
    else: goal_section = "🎯 Дневная норма не рассчитана. Заполните профиль в /settings.\n"

    # Собираем итоговое сообщение
    now_local_str = datetime.now(user_tz).strftime('%d.%m.%Y')
    final_message_parts = [f"📊 **Сводка за сегодня ({now_local_str}, {tz_name}):**\n", goal_section]
    if motivation_message: final_message_parts.append(f"<i>{motivation_message}</i>\n")
    final_message_parts.extend([f"--------------------\n", f"Потреблено сегодня: <b>{total_calories_consumed}</b> ккал\n", entries_text])
    await message.answer("\n".join(part for part in final_message_parts if part), reply_markup=main_action_keyboard())


# --- Отчет за неделю (с исторической нормой) ---
@router.message(Command("week"))
async def handle_week(message: Message):
    """Обработчик команды /week. Показывает отчет за последние 7 дней с исторической нормой."""
    user_id = message.from_user.id
    logger.info(f"Пользователь {user_id} запросил отчет за неделю.")

    if not db.db_pool: logger.warning("Пул БД не инициализирован для /week."); await message.answer("Проблема с БД."); return

    # Получаем пояс и текущий профиль
    tz_name = await db.get_user_timezone(db.db_pool, user_id)
    profile_data = await db.get_user_profile_data(db.db_pool, user_id)
    current_daily_goal = profile_data.get('daily_calorie_goal') if profile_data else None

    try: user_tz = pytz.timezone(tz_name)
    except pytz.UnknownTimeZoneError: logger.warning(f"Некорректный TZ '{tz_name}' для {user_id} в /week. Используется UTC."); user_tz = pytz.utc

    # Получаем записи о еде за период
    num_days_report = 7
    entries = await db.get_last_n_days_entries(db.db_pool, user_id, tz_name, days=num_days_report)

    if not entries: await message.answer(f"📅 За последние {num_days_report} дней записей не найдено.", reply_markup=main_action_keyboard()); return

    # Группируем потребление по локальным датам
    calories_by_day = defaultdict(int)
    dates_with_entries = set() # Множество для уникальных дат с записями
    for entry in entries:
        entry_local_time = entry['entry_timestamp'].astimezone(user_tz)
        entry_date = entry_local_time.date()
        calories_by_day[entry_date] += entry['calories_consumed']
        dates_with_entries.add(entry_date)

    total_calories_consumed = sum(calories_by_day.values())
    days_with_entries_count = len(dates_with_entries)
    average_calories_consumed = round(total_calories_consumed / days_with_entries_count) if days_with_entries_count > 0 else 0

    # --- Расчет исторической нормы ---
    total_norm_period = 0
    average_norm_period = 0
    norm_calculated = False # Флаг, удалось ли рассчитать норму

    # Определяем границы периода для запроса истории
    report_end_date = datetime.now(user_tz).date()
    report_start_date = report_end_date - timedelta(days=num_days_report - 1)

    # Получаем историю норм и дату первой записи
    historical_norms = await db.get_historical_norms(db.db_pool, user_id, report_start_date, report_end_date)
    first_history_date = await db.get_first_goal_history_date(db.db_pool, user_id)

    # Определяем метод расчета
    use_simple_method = not first_history_date or first_history_date > report_start_date

    if use_simple_method:
        # Простой метод: используем текущую норму
        if current_daily_goal:
            total_norm_period = current_daily_goal * days_with_entries_count
            average_norm_period = current_daily_goal
            norm_calculated = True
            logger.debug(f"Расчет нормы (простой метод): тек.норма={current_daily_goal}, дней={days_with_entries_count} -> итого={total_norm_period}")
        else:
            logger.debug("Расчет нормы (простой метод): текущая норма не установлена.")
    else:
        # Сложный метод: используем историю
        logger.debug(f"Расчет нормы (сложный метод). История: {historical_norms}")
        # Преобразуем историю в словарь для удобного поиска
        norms_dict = {record['effective_date']: record['daily_calorie_goal'] for record in historical_norms}
        # Находим самую раннюю дату в истории (она будет ключом)
        history_dates_sorted = sorted(norms_dict.keys())

        # Итерируем по дням, за которые были записи о еде
        applicable_norm_found_for_any_day = False
        for entry_date in sorted(list(dates_with_entries)): # Сортируем даты для логов
            # Ищем последнюю норму, действовавшую НА или ДО этой даты
            applicable_norm = None
            for history_date in reversed(history_dates_sorted): # Идем с конца
                if history_date <= entry_date:
                    applicable_norm = norms_dict[history_date]
                    break
            # Если норма найдена, добавляем к сумме
            if applicable_norm is not None:
                total_norm_period += applicable_norm
                applicable_norm_found_for_any_day = True
                logger.debug(f"  -> Для даты {entry_date}: найдена норма {applicable_norm} (с даты {history_date})")
            else:
                # Если для дня с записью не найдено ни одной предыдущей нормы (очень редкий случай)
                # Используем текущую норму как fallback, если она есть
                if current_daily_goal:
                    total_norm_period += current_daily_goal
                    applicable_norm_found_for_any_day = True # Считаем, что норму применили
                    logger.debug(f"  -> Для даты {entry_date}: норма не найдена в истории, используем текущую {current_daily_goal}")
                else:
                    logger.debug(f"  -> Для даты {entry_date}: норма не найдена в истории и текущая не задана.")


        # Считаем среднее, только если удалось найти норму хотя бы для одного дня
        if applicable_norm_found_for_any_day:
            average_norm_period = round(total_norm_period / days_with_entries_count) if days_with_entries_count > 0 else 0
            norm_calculated = True
            logger.debug(f"Расчет нормы (сложный метод): итого={total_norm_period}, среднее={average_norm_period}")
        else:
             logger.debug("Расчет нормы (сложный метод): не удалось найти применимую норму ни для одного дня.")

    # --- Формируем текст отчета ---
    report_parts = [f"📅 **Отчет за последние {num_days_report} дней ({tz_name}):**\n"]

    # Добавляем разбивку по дням потребления
    report_parts.append("По дням (потреблено):")
    for i in range(num_days_report):
        current_date = report_end_date - timedelta(days=num_days_report - 1 - i) # Идем от начала к концу периода
        cals_consumed = calories_by_day.get(current_date, 0)
        report_parts.append(f"- {current_date.strftime('%d.%m')}: {cals_consumed} ккал")

    # Добавляем итоговые строки
    report_parts.append(f"\n--------------------")
    if norm_calculated:
        report_parts.append(f"Потреблено всего: <b>{total_calories_consumed}</b> ккал (при норме ~{total_norm_period} ккал)")
        report_parts.append(f"Среднесуточное: <b>{average_calories_consumed}</b> ккал (при норме ~{average_norm_period} ккал)")
    else:
        # Если норму рассчитать не удалось
        report_parts.append(f"Потреблено всего: <b>{total_calories_consumed}</b> ккал")
        report_parts.append(f"Среднесуточное: <b>{average_calories_consumed}</b> ккал (за {days_with_entries_count} дн.)")
        report_parts.append(f"<i>(Норма не рассчитана. Заполните профиль в /settings)</i>")

    # Отправляем отчет
    await message.answer("\n".join(report_parts), reply_markup=main_action_keyboard())


# --- Отчет за месяц (с исторической нормой) ---
@router.message(Command("month"))
async def handle_month(message: Message):
    """Обработчик команды /month. Показывает отчет за текущий месяц с исторической нормой."""
    user_id = message.from_user.id
    logger.info(f"Пользователь {user_id} запросил отчет за месяц.")

    if not db.db_pool: logger.warning("Пул БД не инициализирован для /month."); await message.answer("Проблема с БД."); return

    # Получаем пояс и текущий профиль
    tz_name = await db.get_user_timezone(db.db_pool, user_id)
    profile_data = await db.get_user_profile_data(db.db_pool, user_id)
    current_daily_goal = profile_data.get('daily_calorie_goal') if profile_data else None

    try: user_tz = pytz.timezone(tz_name)
    except pytz.UnknownTimeZoneError: logger.warning(f"Некорректный TZ '{tz_name}' для {user_id} в /month. Используется UTC."); user_tz = pytz.utc

    # Получаем записи о еде за месяц
    entries = await db.get_current_month_entries(db.db_pool, user_id, tz_name)

    if not entries: await message.answer(f"🗓️ За текущий месяц записей пока нет.", reply_markup=main_action_keyboard()); return

    # Группируем потребление по дням
    calories_by_day = defaultdict(int)
    dates_with_entries = set()
    for entry in entries:
        entry_local_time = entry['entry_timestamp'].astimezone(user_tz)
        entry_date = entry_local_time.date()
        calories_by_day[entry_date] += entry['calories_consumed']
        dates_with_entries.add(entry_date)

    total_calories_consumed = sum(calories_by_day.values())
    days_with_entries_count = len(dates_with_entries)
    average_calories_consumed = round(total_calories_consumed / days_with_entries_count) if days_with_entries_count > 0 else 0

    # --- Расчет исторической нормы ---
    total_norm_period = 0
    average_norm_period = 0
    norm_calculated = False

    # Определяем границы месяца
    now_local = datetime.now(user_tz)
    report_start_date = date(now_local.year, now_local.month, 1)
    report_end_date = now_local.date() # Конец - сегодняшний день

    # Получаем историю и первую дату
    historical_norms = await db.get_historical_norms(db.db_pool, user_id, report_start_date, report_end_date)
    first_history_date = await db.get_first_goal_history_date(db.db_pool, user_id)

    use_simple_method = not first_history_date or first_history_date > report_start_date

    if use_simple_method:
        if current_daily_goal:
            total_norm_period = current_daily_goal * days_with_entries_count
            average_norm_period = current_daily_goal
            norm_calculated = True
            logger.debug(f"Расчет нормы месяца (простой): тек.={current_daily_goal}, дней={days_with_entries_count} -> итого={total_norm_period}")
        else: logger.debug("Расчет нормы месяца (простой): текущая норма не задана.")
    else:
        logger.debug(f"Расчет нормы месяца (сложный). История: {historical_norms}")
        norms_dict = {record['effective_date']: record['daily_calorie_goal'] for record in historical_norms}
        history_dates_sorted = sorted(norms_dict.keys())
        applicable_norm_found_for_any_day = False
        for entry_date in dates_with_entries: # Итерируем только по дням с записями
            applicable_norm = None
            for history_date in reversed(history_dates_sorted):
                if history_date <= entry_date:
                    applicable_norm = norms_dict[history_date]
                    break
            if applicable_norm is not None:
                total_norm_period += applicable_norm
                applicable_norm_found_for_any_day = True
                # logger.debug(f"  -> Для {entry_date}: норма {applicable_norm} (с {history_date})")
            else:
                if current_daily_goal:
                    total_norm_period += current_daily_goal
                    applicable_norm_found_for_any_day = True
                    # logger.debug(f"  -> Для {entry_date}: норма не найдена, используем текущую {current_daily_goal}")
                # else: logger.debug(f"  -> Для {entry_date}: норма не найдена, текущая не задана.")

        if applicable_norm_found_for_any_day:
            average_norm_period = round(total_norm_period / days_with_entries_count) if days_with_entries_count > 0 else 0
            norm_calculated = True
            logger.debug(f"Расчет нормы месяца (сложный): итого={total_norm_period}, среднее={average_norm_period}")
        else: logger.debug("Расчет нормы месяца (сложный): не удалось найти применимую норму.")


    # --- Формируем текст отчета ---
    month_number = now_local.month
    month_name = RUSSIAN_MONTHS.get(month_number, f"Месяц {month_number}")
    report_parts = [f"🗓️ **Отчет за {month_name} {now_local.year} ({tz_name}):**\n"]
    report_parts.append(f"--------------------")
    if norm_calculated:
        report_parts.append(f"Потреблено всего: <b>{total_calories_consumed}</b> ккал (при норме ~{total_norm_period} ккал)")
        report_parts.append(f"Среднесуточное: <b>{average_calories_consumed}</b> ккал (при норме ~{average_norm_period} ккал)")
    else:
        report_parts.append(f"Потреблено всего: <b>{total_calories_consumed}</b> ккал")
        report_parts.append(f"Среднесуточное: <b>{average_calories_consumed}</b> ккал (за {days_with_entries_count} дн.)")
        report_parts.append(f"<i>(Норма не рассчитана. Заполните профиль в /settings)</i>")

    # Отправляем отчет
    await message.answer("\n".join(report_parts), reply_markup=main_action_keyboard())

