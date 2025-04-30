import logging
# Импортируем необходимые модули для работы с датой/временем и часовыми поясами
from datetime import datetime, time, date, timedelta
import pytz # <--- Добавили pytz
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

# Настраиваем логирование для этого модуля
logger = logging.getLogger(__name__)

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
    """Обработчик команды /today. Показывает сводку за текущий день."""
    user_id = message.from_user.id
    logger.info(f"Пользователь {user_id} запросил сводку за сегодня.")

    # Проверяем наличие пула соединений с БД
    if not db.db_pool:
        logger.warning("Пул соединений с БД не инициализирован при обработке /today.")
        await message.answer("Возникла проблема с подключением к базе данных. Попробуйте позже.")
        return

    # Получаем часовой пояс пользователя из БД
    tz_name = await db.get_user_timezone(db.db_pool, user_id)
    try:
        # Пытаемся создать объект часового пояса
        user_tz = pytz.timezone(tz_name)
    except pytz.UnknownTimeZoneError:
        # Если пояс некорректный, используем UTC и логируем предупреждение
        logger.warning(f"Некорректный часовой пояс '{tz_name}' для {user_id} в /today. Используется UTC.")
        user_tz = pytz.utc # Используем UTC как fallback

    # Получаем записи о еде за сегодня с учетом часового пояса
    entries = await db.get_todays_food_entries(db.db_pool, user_id, tz_name)

    # --- ОТЛАДОЧНЫЙ ЛОГ: Записи, полученные для /today ---
    # logger.debug(f"/today для {user_id} (TZ: {tz_name}). Получено записей: {len(entries)}")
    # for i, entry in enumerate(entries):
    #     logger.debug(f"  Запись {i+1}: UTC={entry['entry_timestamp']}, Локальное={entry['entry_timestamp'].astimezone(user_tz)}, Ккал={entry['calories_consumed']}")
    # --- КОНЕЦ ЛОГА ---

    # Считаем общую калорийность и формируем список продуктов
    total_calories = 0
    entries_text_parts = []

    if entries:
        # Если записи есть, проходим по ним
        for entry in entries:
            # Экранируем название продукта для безопасного вывода в HTML
            product_name_safe = escape(entry['product_name'])
            # Формируем строку для продукта
            entries_text_parts.append(
                f"- {product_name_safe} ({entry['weight_grams']}г): {entry['calories_consumed']} ккал"
            )
            # Суммируем калории
            total_calories += entry['calories_consumed']
        # Объединяем строки продуктов в один текст
        entries_text = "\n".join(entries_text_parts)
    else:
        # Если записей нет
        entries_text = "Пока ничего не добавлено."

    # Получаем текущую дату в часовом поясе пользователя для отображения
    now_local_str = datetime.now(user_tz).strftime('%d.%m.%Y')

    # Отправляем итоговое сообщение со сводкой и основной клавиатурой
    await message.answer(
        f"📊 **Сводка за сегодня ({now_local_str}, {tz_name}):**\n\n" # Показываем дату и пояс
        f"{entries_text}\n\n"
        f"--------------------\n"
        f"**Всего калорий за сегодня: {total_calories}**",
        reply_markup=main_action_keyboard() # Показываем клавиатуру с кнопкой "Добавить"
    )

# --- Отчет за неделю ---
@router.message(Command("week"))
async def handle_week(message: Message):
    """Обработчик команды /week. Показывает отчет за последние 7 дней."""
    user_id = message.from_user.id
    logger.info(f"Пользователь {user_id} запросил отчет за неделю.")

    # Проверка подключения к БД
    if not db.db_pool:
        logger.warning("Пул соединений с БД не инициализирован при обработке /week.")
        await message.answer("Возникла проблема с подключением к базе данных. Попробуйте позже.")
        return

    # Получаем часовой пояс пользователя
    tz_name = await db.get_user_timezone(db.db_pool, user_id)
    try:
        user_tz = pytz.timezone(tz_name)
    except pytz.UnknownTimeZoneError:
        logger.warning(f"Некорректный часовой пояс '{tz_name}' для {user_id} в /week. Используется UTC.")
        user_tz = pytz.utc

    # Получаем записи за последние 7 дней
    num_days = 7
    entries = await db.get_last_n_days_entries(db.db_pool, user_id, tz_name, days=num_days)

    # --- ОТЛАДОЧНЫЙ ЛОГ 1: Выводим полученные записи ---
    # logger.debug(f"Отчет /week для {user_id} (TZ: {tz_name}). Получено записей: {len(entries)}")
    # for i, entry in enumerate(entries):
    #     logger.debug(f"  Запись {i+1}: UTC={entry['entry_timestamp']}, Калории={entry['calories_consumed']}")
    # --- КОНЕЦ ОТЛАДОЧНОГО ЛОГА 1 ---

    # Если записей нет, сообщаем об этом
    if not entries:
        await message.answer(
            f"📅 За последние {num_days} дней записей не найдено.",
            reply_markup=main_action_keyboard()
        )
        return

    # Группируем калории по дням (в локальном времени пользователя)
    calories_by_day = defaultdict(int) # Словарь для сумм калорий по датам
    total_calories_period = 0 # Общая сумма за период
    for entry in entries:
        # Конвертируем UTC timestamp из БД в локальное время пользователя
        entry_local_time = entry['entry_timestamp'].astimezone(user_tz)
        entry_date = entry_local_time.date() # Получаем локальную дату
        # Добавляем калории к сумме для этой даты
        calories_by_day[entry_date] += entry['calories_consumed']
        # Увеличиваем общую сумму
        total_calories_period += entry['calories_consumed']
        # --- ОТЛАДОЧНЫЙ ЛОГ 2: Выводим локальную дату для каждой записи ---
        # logger.debug(f"    -> Запись UTC={entry['entry_timestamp']} -> Локальное время: {entry_local_time}, Локальная дата: {entry_date}")
        # --- КОНЕЦ ОТЛАДОЧНОГО ЛОГА 2 ---


    # Считаем количество дней, за которые были записи (может быть меньше num_days)
    days_with_entries = len(calories_by_day)
    # Считаем среднее значение (только за дни с записями)
    average_calories = round(total_calories_period / days_with_entries) if days_with_entries > 0 else 0

    # --- ОТЛАДОЧНЫЙ ЛОГ 3: Выводим сгруппированные данные ---
    # logger.debug(f"Отчет /week для {user_id}. Сгруппировано по дням: {dict(calories_by_day)}")
    # logger.debug(f"  -> Дней с записями: {days_with_entries}, Всего калорий: {total_calories_period}, Среднее: {average_calories}")
    # --- КОНЕЦ ОТЛАДОЧНОГО ЛОГА 3 ---


    # Формируем текст отчета
    report_parts = [f"📅 **Отчет за последние {num_days} дней ({tz_name}):**\n"]
    # Секция с детализацией по дням закомментирована, можно включить при необходимости
    report_parts.append("По дням:")
    today_local = datetime.now(user_tz).date()
    for i in range(num_days):
        current_date = today_local - timedelta(days=i)
        cals = calories_by_day.get(current_date, 0)
        report_parts.append(f"- {current_date.strftime('%d.%m.%Y')}: {cals} ккал")

    report_parts.append(f"\n--------------------")
    report_parts.append(f"Общая калорийность: {total_calories_period} ккал")
    report_parts.append(f"Среднесуточная: {average_calories} ккал (за {days_with_entries} дн.)") # Указываем, за сколько дней считалось среднее

    # Отправляем отчет
    await message.answer(
        "\n".join(report_parts),
        reply_markup=main_action_keyboard()
    )


# --- Отчет за месяц ---
@router.message(Command("month"))
async def handle_month(message: Message):
    """Обработчик команды /month. Показывает отчет за текущий календарный месяц."""
    user_id = message.from_user.id
    logger.info(f"Пользователь {user_id} запросил отчет за месяц.")

    # Проверка подключения к БД
    if not db.db_pool:
        logger.warning("Пул соединений с БД не инициализирован при обработке /month.")
        await message.answer("Возникла проблема с подключением к базе данных. Попробуйте позже.")
        return

    # Получаем часовой пояс пользователя
    tz_name = await db.get_user_timezone(db.db_pool, user_id)
    try:
        user_tz = pytz.timezone(tz_name)
    except pytz.UnknownTimeZoneError:
        logger.warning(f"Некорректный часовой пояс '{tz_name}' для {user_id} в /month. Используется UTC.")
        user_tz = pytz.utc

    # Получаем записи за текущий месяц
    entries = await db.get_current_month_entries(db.db_pool, user_id, tz_name)

    # Если записей нет
    if not entries:
        await message.answer(
            f"🗓️ За текущий месяц записей пока нет.",
            reply_markup=main_action_keyboard()
        )
        return

    # Группируем калории по дням (в локальном времени пользователя)
    calories_by_day = defaultdict(int)
    total_calories_period = 0
    for entry in entries:
        entry_local_time = entry['entry_timestamp'].astimezone(user_tz)
        entry_date = entry_local_time.date()
        calories_by_day[entry_date] += entry['calories_consumed']
        total_calories_period += entry['calories_consumed']

    # Считаем количество дней с записями и среднее значение
    days_with_entries = len(calories_by_day)
    average_calories = round(total_calories_period / days_with_entries) if days_with_entries > 0 else 0

    # Получаем название месяца и год в локальном времени
    now_local = datetime.now(user_tz)
    month_number = now_local.month
    # Берем русское название месяца из словаря
    month_name = RUSSIAN_MONTHS.get(month_number, f"Месяц {month_number}") # Fallback на номер месяца

    # Формируем текст отчета
    report_parts = [f"🗓️ **Отчет за {month_name} {now_local.year} ({tz_name}):**\n"]
    report_parts.append(f"--------------------")
    report_parts.append(f"Общая калорийность: {total_calories_period} ккал")
    report_parts.append(f"Среднесуточная: {average_calories} ккал (за {days_with_entries} дн.)")

    # Отправляем отчет
    await message.answer(
        "\n".join(report_parts),
        reply_markup=main_action_keyboard()
    )

