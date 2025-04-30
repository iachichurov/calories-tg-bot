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
        await message.answer("Возникла проблема с подключением к базе данных. Попробуйте позже.")
        return

    # --- Получаем часовой пояс и данные профиля пользователя ---
    tz_name = await db.get_user_timezone(db.db_pool, user_id)
    profile_data = await db.get_user_profile_data(db.db_pool, user_id) # Получаем профиль

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


    # Считаем общую калорийность потребленную за сегодня
    total_calories_consumed = sum(entry['calories_consumed'] for entry in entries)

    # Формируем список продуктов
    entries_text_parts = []
    if entries:
        # logger.debug(f"Начинаем цикл обработки {len(entries)} записей для /today...") # <-- Лог перед циклом
        for i, entry in enumerate(entries):
            try:
                # --- ОТЛАДОЧНЫЙ ЛОГ ВНУТРИ ЦИКЛА ---
                # logger.debug(f"  Обработка записи {i+1}: Данные = {dict(entry)}")
                # --- КОНЕЦ ЛОГА ---

                product_name = entry['product_name']
                weight = entry['weight_grams']
                calories = entry['calories_consumed']

                # --- ОТЛАДОЧНЫЙ ЛОГ ПОЛЕЙ ---
                # logger.debug(f"    -> Продукт: '{product_name}', Вес: {weight}, Ккал: {calories}")
                # --- КОНЕЦ ЛОГА ---

                product_name_safe = escape(product_name) # Экранируем для HTML
                formatted_string = f"- {product_name_safe} ({weight}г): {calories} ккал"

                # --- ОТЛАДОЧНЫЙ ЛОГ СТРОКИ ---
                # logger.debug(f"    -> Сформированная строка: '{formatted_string}'")
                # --- КОНЕЦ ЛОГА ---

                entries_text_parts.append(formatted_string)
                total_calories_consumed += calories # Исправлено: было total_calories += calories
            except KeyError as e:
                logger.error(f"Ошибка KeyError при доступе к полю записи {i+1}: {e}. Данные записи: {dict(entry)}")
            except Exception as e:
                 logger.error(f"Неожиданная ошибка при обработке записи {i+1}: {e}. Данные записи: {dict(entry)}", exc_info=True)

        # logger.debug(f"Цикл завершен. entries_text_parts: {entries_text_parts}, total_calories_consumed: {total_calories_consumed}") # <-- Лог после цикла
        entries_text = "\n".join(entries_text_parts)
    else:
        entries_text = "Пока ничего не добавлено."

    # --- Формируем блок с нормой и мотивацией ---
    goal_section = ""          # Секция с отображением нормы
    motivation_message = ""    # Мотивационное сообщение
    daily_goal_calories = None # Рассчитанная норма калорий

    if profile_data:
        # Пытаемся получить норму из профиля (она должна быть рассчитана и сохранена в settings)
        daily_goal_calories = profile_data.get('daily_calorie_goal') # Берем уже рассчитанную норму
        user_goal = profile_data.get('goal') # Берем цель пользователя

        if daily_goal_calories: # Если норма была успешно рассчитана и сохранена
            goal_section = f"🎯 Ваша дневная норма: ~<b>{daily_goal_calories}</b> ккал\n"

            # Формируем мотивацию, только если у пользователя установлена цель и есть норма
            if user_goal:
                diff = total_calories_consumed - daily_goal_calories
                if user_goal == 'deficit':
                    if diff <= 0: motivation_message = "👍 Ты молодец! Продолжай в том же духе." # Поощрение
                    else: motivation_message = f"⚠️ Превышение нормы на {diff} ккал. Не сдавайся, у тебя получится!" # Мотивация
                elif user_goal == 'maintenance':
                    # Считаем нормой диапазон +/- 5% от цели (можно настроить)
                    if abs(diff) < daily_goal_calories * 0.05: motivation_message = "✅ Отлично! Норма калорий соблюдена."
                    elif diff > 0: motivation_message = f"📈 Небольшое превышение нормы (+{diff} ккал)."
                    else: motivation_message = f"📉 Немного не добрали до нормы ({diff} ккал)."
                elif user_goal == 'surplus':
                    if diff >= 0: motivation_message = "💪 Отличная работа! Вы в профиците." # Поощрение
                    else: motivation_message = f"⏳ Нужно еще {-diff} ккал для достижения профицита." # Мотивация
        else:
            # Если норма не рассчитана (не хватает данных в профиле)
             goal_section = "🎯 Дневная норма не рассчитана. Заполните профиль в /settings.\n"
    else:
        # Если данных профиля вообще нет
        goal_section = "🎯 Дневная норма не рассчитана. Заполните профиль в /settings.\n"


    # --- Собираем итоговое сообщение ---
    now_local_str = datetime.now(user_tz).strftime('%d.%m.%Y') # Дата в локальном поясе
    # Собираем части сообщения, чтобы легко добавлять/убирать блоки
    final_message_parts = [
        f"📊 **Сводка за сегодня ({now_local_str}, {tz_name}):**\n",
        goal_section # Добавляем секцию с нормой (или сообщением о ее отсутствии)
    ]
    # Добавляем мотивацию, только если она сформировалась
    if motivation_message:
        final_message_parts.append(f"<i>{motivation_message}</i>\n") # Курсивом для выделения

    # Добавляем разделитель, сумму потребленных калорий и список продуктов
    final_message_parts.extend([
        f"--------------------\n"
        f"Потреблено сегодня: <b>{total_calories_consumed}</b> ккал\n", # Используем total_calories_consumed
        entries_text # Список продуктов или сообщение об их отсутствии
    ])

    # --- ОТЛАДОЧНЫЙ ЛОГ ПЕРЕД ОТПРАВКОЙ ---
    # logger.debug(f"Отправка сообщения /today. entries_text='{entries_text}', total_calories_consumed={total_calories_consumed}")
    # --- КОНЕЦ ЛОГА ---

    # Отправляем собранное сообщение
    await message.answer(
        "\n".join(part for part in final_message_parts if part), # Собираем части, убирая пустые строки
        reply_markup=main_action_keyboard() # Показываем основную клавиатуру
    )

# --- Отчет за неделю ---
@router.message(Command("week"))
async def handle_week(message: Message):
    """Обработчик команды /week. Показывает отчет за последние 7 дней."""
    user_id = message.from_user.id; logger.info(f"Пользователь {user_id} запросил отчет за неделю.")
    # Проверка подключения к БД
    if not db.db_pool: logger.warning("Пул БД не инициализирован для /week."); await message.answer("Проблема с БД."); return
    # Получаем часовой пояс
    tz_name = await db.get_user_timezone(db.db_pool, user_id)
    try: user_tz = pytz.timezone(tz_name)
    except pytz.UnknownTimeZoneError: logger.warning(f"Некорректный TZ '{tz_name}' для {user_id} в /week. Используется UTC."); user_tz = pytz.utc
    # Получаем записи
    num_days = 7; entries = await db.get_last_n_days_entries(db.db_pool, user_id, tz_name, days=num_days)
    # Если записей нет
    if not entries: await message.answer(f"📅 За последние {num_days} дней записей не найдено.", reply_markup=main_action_keyboard()); return
    # Группируем по дням
    calories_by_day = defaultdict(int); total_calories_period = 0
    for entry in entries:
        entry_local_time = entry['entry_timestamp'].astimezone(user_tz); entry_date = entry_local_time.date()
        calories_by_day[entry_date] += entry['calories_consumed']; total_calories_period += entry['calories_consumed']
        # logger.debug(f"  /week: Запись UTC={entry['entry_timestamp']} -> Лок.дата={entry_date}, Ккал={entry['calories_consumed']}")
    # Считаем среднее
    days_with_entries = len(calories_by_day); average_calories = round(total_calories_period / days_with_entries) if days_with_entries > 0 else 0
    # logger.debug(f"/week для {user_id}. Сгруппировано: {dict(calories_by_day)}")
    # logger.debug(f"  -> Дней: {days_with_entries}, Всего: {total_calories_period}, Среднее: {average_calories}")
    # Формируем отчет
    report_parts = [f"📅 **Отчет за последние {num_days} дней ({tz_name}):**\n", f"\n--------------------", f"Общая калорийность: {total_calories_period} ккал", f"Среднесуточная: {average_calories} ккал (за {days_with_entries} дн.)"]
    # Отправляем
    await message.answer("\n".join(report_parts), reply_markup=main_action_keyboard())

# --- Отчет за месяц ---
@router.message(Command("month"))
async def handle_month(message: Message):
    """Обработчик команды /month. Показывает отчет за текущий календарный месяц."""
    user_id = message.from_user.id; logger.info(f"Пользователь {user_id} запросил отчет за месяц.")
    # Проверка БД
    if not db.db_pool: logger.warning("Пул БД не инициализирован для /month."); await message.answer("Проблема с БД."); return
    # Получаем пояс
    tz_name = await db.get_user_timezone(db.db_pool, user_id)
    try: user_tz = pytz.timezone(tz_name)
    except pytz.UnknownTimeZoneError: logger.warning(f"Некорректный TZ '{tz_name}' для {user_id} в /month. Используется UTC."); user_tz = pytz.utc
    # Получаем записи
    entries = await db.get_current_month_entries(db.db_pool, user_id, tz_name)
    # Если нет записей
    if not entries: await message.answer(f"🗓️ За текущий месяц записей пока нет.", reply_markup=main_action_keyboard()); return
    # Группируем
    calories_by_day = defaultdict(int); total_calories_period = 0
    for entry in entries:
        entry_local_time = entry['entry_timestamp'].astimezone(user_tz); entry_date = entry_local_time.date()
        calories_by_day[entry_date] += entry['calories_consumed']; total_calories_period += entry['calories_consumed']
    # Считаем среднее
    days_with_entries = len(calories_by_day); average_calories = round(total_calories_period / days_with_entries) if days_with_entries > 0 else 0
    # Получаем имя месяца
    now_local = datetime.now(user_tz); month_number = now_local.month; month_name = RUSSIAN_MONTHS.get(month_number, f"Месяц {month_number}")
    # Формируем отчет
    report_parts = [f"🗓️ **Отчет за {month_name} {now_local.year} ({tz_name}):**\n", f"--------------------", f"Общая калорийность: {total_calories_period} ккал", f"Среднесуточная: {average_calories} ккал (за {days_with_entries} дн.)"]
    # Отправляем
    await message.answer("\n".join(report_parts), reply_markup=main_action_keyboard())

