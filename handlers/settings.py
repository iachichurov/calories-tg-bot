import logging
import pytz
from html import escape
# Используем date из datetime для работы с датой
from datetime import date, datetime, UTC
from aiogram import Router, F, Bot
from aiogram.filters import Command, StateFilter
from aiogram.types import Message, ReplyKeyboardRemove, CallbackQuery
from aiogram.fsm.context import FSMContext
from contextlib import suppress # Для подавления ошибок при редактировании/удалении сообщений
from aiogram.exceptions import TelegramBadRequest # Для обработки ошибок API при редактировании

# Импортируем состояния, клавиатуры, функции БД, утилиты
from states import Settings # Используем состояния для настроек
from keyboards import (
    cancel_keyboard, main_action_keyboard, settings_main_keyboard,
    select_goal_keyboard, select_gender_keyboard,
    SETTINGS_ACTION_CALLBACK_PREFIX, GENDER_SELECT_CALLBACK_PREFIX,
    GOAL_SELECT_CALLBACK_PREFIX, CANCEL_TEXT,
    SETTINGS_SHOW_MENU_ACTION # Импортируем новое действие
)
import database as db
import utils # Наш модуль с расчетами
from .reports import handle_today # Для показа сводки после

# Настраиваем логирование
logger = logging.getLogger(__name__)

# Создаем роутер для обработчиков настроек
router = Router()

# Ссылка на список часовых поясов (если оставляем эту настройку)
TIMEZONE_LIST_URL = "https://en.wikipedia.org/wiki/List_of_tz_database_time_zones"

# --- Вспомогательная функция для пересчета и сохранения нормы ---
async def recalculate_and_save_goal(user_id: int, state: FSMContext):
    """
    Получает актуальные данные профиля пользователя из БД,
    вызывает функции расчета LBM и калорий,
    сохраняет рассчитанную норму (daily_calorie_goal) в БД users
    И ДОБАВЛЯЕТ ЗАПИСЬ В goal_history.
    Возвращает рассчитанную норму калорий или None, если расчет не удался.
    """
    if not db.db_pool:
        logger.error(f"Нет подключения к БД для пересчета нормы {user_id}")
        return None

    profile_data = await db.get_user_profile_data(db.db_pool, user_id)
    if not profile_data:
        logger.warning(f"Нет данных профиля для пересчета нормы {user_id}")
        await db.update_user_daily_goal(db.db_pool, user_id, None)
        return None

    # Извлекаем данные из профиля
    weight = profile_data.get('current_weight')
    height = profile_data.get('height')
    gender = profile_data.get('gender')
    goal = profile_data.get('goal')

    # Проверяем наличие всех данных для расчета
    if not all([weight, height, gender, goal]):
        logger.info(f"Не все данные профиля заполнены для {user_id}. Норма не рассчитана.")
        await db.update_user_daily_goal(db.db_pool, user_id, None)
        return None

    # Расчет LBM
    lbm = utils.calculate_lbm(weight_kg=float(weight), height_cm=height, gender=gender)
    if lbm is None:
        logger.warning(f"Не удалось рассчитать LBM для {user_id}. Норма не рассчитана.")
        await db.update_user_daily_goal(db.db_pool, user_id, None)
        return None

    # Расчет калорий
    _, calories = utils.calculate_target_macros_and_calories(lbm=lbm, goal=goal) or (None, None)
    if calories is None:
        logger.warning(f"Не удалось рассчитать калории для {user_id}. Норма не рассчитана.")
        await db.update_user_daily_goal(db.db_pool, user_id, None)
        return None

    # Сохранение нормы и запись в историю
    try:
        await db.update_user_daily_goal(db.db_pool, user_id, calories)
        today_utc_date = datetime.now(UTC).date()
        await db.add_goal_history_entry(db.db_pool, user_id, today_utc_date, calories)
        logger.info(f"Норма калорий для {user_id} пересчитана ({calories} ккал) и сохранена.")
        return calories
    except Exception as e:
        logger.error(f"Ошибка при сохранении нормы или истории для {user_id}: {e}", exc_info=True)
        await db.update_user_daily_goal(db.db_pool, user_id, None) # Пытаемся сбросить норму
        return None


# --- Функция для отображения главного меню настроек ---
async def show_settings_menu(message_or_callback: Message | CallbackQuery, state: FSMContext):
    """
    Отображает текущие настройки профиля и инлайн-клавиатуру
    с кнопками для их изменения.
    """
    user_id = message_or_callback.from_user.id
    # Определяем метод ответа (новое сообщение или редактирование)
    if isinstance(message_or_callback, Message):
        answer_method = message_or_callback.answer
    else: # CallbackQuery
        answer_method = message_or_callback.message.answer
        # Отвечаем на callback, чтобы убрать "часики"
        await message_or_callback.answer()

    # Получаем и форматируем текущие данные профиля
    profile_data = None
    current_goal_text = "Не установлена"
    current_gender_text = "Не указан"
    current_height_text = "Не указан"
    current_weight_text = "Не указан"
    current_norm_text = "Не рассчитана"

    if db.db_pool:
        profile_data = await db.get_user_profile_data(db.db_pool, user_id)
        if profile_data:
            goal = profile_data.get('goal')
            if goal == 'deficit': current_goal_text = "📉 Дефицит"
            elif goal == 'maintenance': current_goal_text = "維持 Поддержание"
            elif goal == 'surplus': current_goal_text = "📈 Профицит"

            gender = profile_data.get('gender')
            if gender == 'male': current_gender_text = "👨 Мужской"
            elif gender == 'female': current_gender_text = "👩 Женский"

            height = profile_data.get('height')
            if height: current_height_text = f"{height} см"

            weight = profile_data.get('current_weight')
            if weight: current_weight_text = f"{weight:.1f} кг"

            norm = profile_data.get('daily_calorie_goal')
            if norm:
                current_norm_text = f"~<b>{norm}</b> ккал/день"
            else:
                # Пробуем пересчитать, если нормы нет, но данные есть
                if all([weight, height, gender, goal]):
                     norm = await recalculate_and_save_goal(user_id, state)
                     if norm: current_norm_text = f"~<b>{norm}</b> ккал/день"
                     else: current_norm_text = "Ошибка расчета"
                else:
                     current_norm_text = "Не рассчитана (заполните профиль)"

    # Собираем текст сообщения
    settings_text = (
        f"⚙️ **Настройки профиля:**\n\n"
        f"🎯 Ваша цель: <b>{current_goal_text}</b>\n"
        f"🧍 Ваш пол: <b>{current_gender_text}</b>\n"
        f"📏 Ваш рост: <b>{current_height_text}</b>\n"
        f"⚖️ Ваш вес: <b>{current_weight_text}</b>\n\n"
        f"📊 Расчетная норма: {current_norm_text}\n\n"
        f"Выберите, что хотите изменить:"
    )

    # Отправляем или редактируем сообщение
    if isinstance(message_or_callback, CallbackQuery):
         with suppress(TelegramBadRequest): # Игнорируем ошибку (сообщение не изменилось и т.д.)
              await message_or_callback.message.edit_text(
                  settings_text,
                  reply_markup=settings_main_keyboard()
              )
              await state.set_state(Settings.waiting_for_action)
              return # Выходим после успешного редактирования

    # Отправляем новое сообщение, если это было не CallbackQuery или редактирование не удалось
    await answer_method(settings_text, reply_markup=settings_main_keyboard())
    await state.set_state(Settings.waiting_for_action)


# --- Обработчики команды /settings и /setweight ---
@router.message(Command("settings"), StateFilter(None))
async def handle_settings_command(message: Message, state: FSMContext):
    """Отображает меню настроек профиля по команде /settings."""
    user_id = message.from_user.id
    logger.info(f"Пользователь {user_id} вызвал /settings.")
    await show_settings_menu(message, state)

@router.message(Command("setweight"), StateFilter(None))
async def handle_setweight_command(message: Message, state: FSMContext):
    """Начинает процесс установки веса по команде /setweight."""
    user_id = message.from_user.id
    logger.info(f"Пользователь {user_id} вызвал /setweight.")
    await message.answer(
        "Введите ваш текущий вес в килограммах (например, 75.5):",
        reply_markup=cancel_keyboard()
    )
    await state.set_state(Settings.waiting_for_weight)

# --- Обработчики CallbackQuery для основного меню настроек ---
@router.callback_query(
    F.data.startswith(SETTINGS_ACTION_CALLBACK_PREFIX),
    StateFilter(Settings.waiting_for_action)
)
async def handle_settings_action(callback: CallbackQuery, state: FSMContext):
    """Обрабатывает нажатия кнопок в главном меню настроек И возврат из подменю."""
    action = callback.data.split(":")[1]
    user_id = callback.from_user.id
    message = callback.message

    # Обработка возврата в главное меню из подменю
    if action == SETTINGS_SHOW_MENU_ACTION:
        logger.info(f"Пользователь {user_id} вернулся в главное меню настроек.")
        # Просто показываем главное меню (оно само отредактирует сообщение)
        await show_settings_menu(callback, state)
        return # Выходим, т.к. действие выполнено

    # Обработка кнопки "Закрыть настройки"
    if action == "back":
        logger.info(f"Пользователь {user_id} нажал 'Закрыть настройки'.")
        # Убираем инлайн-клавиатуру настроек
        with suppress(TelegramBadRequest):
            await message.edit_reply_markup(reply_markup=None)
        # Очищаем состояние FSM
        await state.clear()
        # Отправляем сообщение о закрытии и основную клавиатуру
        await message.answer("Настройки закрыты.", reply_markup=main_action_keyboard())
        # Отвечаем на callback и выходим
        await callback.answer()
        return

    # Для других действий сначала убираем кнопки главного меню
    with suppress(TelegramBadRequest):
        await message.edit_reply_markup(reply_markup=None)

    # Обработка остальных действий
    if action == "change_goal":
        logger.info(f"Пользователь {user_id} выбрал изменить цель.")
        await message.answer("Выберите вашу основную цель:", reply_markup=select_goal_keyboard())
        # Остаемся в состоянии waiting_for_action, ждем нажатия инлайн-кнопки цели
        await state.set_state(Settings.waiting_for_action)
    elif action == "change_gender":
        logger.info(f"Пользователь {user_id} выбрал изменить пол.")
        await message.answer("Выберите ваш пол:", reply_markup=select_gender_keyboard())
        await state.set_state(Settings.waiting_for_action) # Ждем нажатия инлайн-кнопки пола
    elif action == "change_height":
        logger.info(f"Пользователь {user_id} выбрал изменить рост.")
        await message.answer("Введите ваш рост в сантиметрах (например, 180):", reply_markup=cancel_keyboard())
        await state.set_state(Settings.waiting_for_height) # Переходим в состояние ожидания роста
    elif action == "change_weight":
        logger.info(f"Пользователь {user_id} выбрал изменить вес.")
        await message.answer("Введите ваш текущий вес в килограммах (например, 75.5):", reply_markup=cancel_keyboard())
        await state.set_state(Settings.waiting_for_weight) # Переходим в состояние ожидания веса

    await callback.answer() # Отвечаем на callback для всех действий, кроме "Назад"

# --- Обработчики CallbackQuery для выбора цели и пола ---
@router.callback_query(
    F.data.startswith(GOAL_SELECT_CALLBACK_PREFIX),
    StateFilter(Settings.waiting_for_action)
)
async def handle_goal_selection(callback: CallbackQuery, state: FSMContext):
    """Обрабатывает выбор цели."""
    goal = callback.data.split(":")[1]
    user_id = callback.from_user.id
    message = callback.message

    # Убираем клавиатуру выбора цели
    with suppress(TelegramBadRequest):
        await message.edit_reply_markup(reply_markup=None)

    goal_to_save = goal if goal != "none" else None # Сохраняем NULL, если выбрано "Не устанавливать"

    if db.db_pool:
        success = await db.update_user_profile_field(db.db_pool, user_id, "goal", goal_to_save)
        if success:
            logger.info(f"Цель для {user_id} установлена на '{goal}'. Пересчет нормы...")
            await recalculate_and_save_goal(user_id, state) # Пересчитываем норму
            await message.answer(f"✅ Цель обновлена!")
            await show_settings_menu(callback, state) # Показываем обновленное меню настроек
        else:
            await message.answer("Не удалось обновить цель. Попробуйте позже.")
            await show_settings_menu(callback, state) # Возвращаем в меню
    else:
        # Ошибка подключения к БД
        await message.answer("Ошибка подключения к БД.")
        await state.clear(); await handle_today(message) # Выходим из настроек

    await callback.answer()

@router.callback_query(
    F.data.startswith(GENDER_SELECT_CALLBACK_PREFIX),
    StateFilter(Settings.waiting_for_action)
)
async def handle_gender_selection(callback: CallbackQuery, state: FSMContext):
    """Обрабатывает выбор пола."""
    gender = callback.data.split(":")[1] # 'male' или 'female'
    user_id = callback.from_user.id
    message = callback.message

    # Убираем клавиатуру выбора пола
    with suppress(TelegramBadRequest):
        await message.edit_reply_markup(reply_markup=None)

    if db.db_pool:
        success = await db.update_user_profile_field(db.db_pool, user_id, "gender", gender)
        if success:
            logger.info(f"Пол для {user_id} установлен на '{gender}'. Пересчет нормы...")
            await recalculate_and_save_goal(user_id, state) # Пересчитываем норму
            await message.answer(f"✅ Пол обновлен!")
            await show_settings_menu(callback, state) # Показываем обновленное меню
        else:
            await message.answer("Не удалось обновить пол. Попробуйте позже.")
            await show_settings_menu(callback, state)
    else:
        await message.answer("Ошибка подключения к БД.")
        await state.clear(); await handle_today(message)

    await callback.answer()

# --- Обработчики ввода роста и веса ---
@router.message(StateFilter(Settings.waiting_for_height), F.text)
async def process_height_input(message: Message, state: FSMContext):
    """Обрабатывает ввод роста."""
    user_id = message.from_user.id
    # Валидация ввода
    try:
        height = int(message.text.strip())
        if not (100 <= height <= 250): # Простая проверка диапазона
            raise ValueError("Рост должен быть в разумных пределах (100-250 см).")
    except (ValueError, AssertionError):
        await message.reply("Пожалуйста, введите рост целым числом от 100 до 250 см. Или /cancel")
        return # Остаемся в том же состоянии

    # Обновление в БД
    if db.db_pool:
        success = await db.update_user_profile_field(db.db_pool, user_id, "height", height)
        if success:
            logger.info(f"Рост для {user_id} установлен на {height} см. Пересчет нормы...")
            await recalculate_and_save_goal(user_id, state) # Пересчитываем норму
            await message.answer(f"✅ Рост обновлен!", reply_markup=ReplyKeyboardRemove())
            await show_settings_menu(message, state) # Возвращаемся в меню настроек
        else:
            await message.answer("Не удалось обновить рост. Попробуйте позже.", reply_markup=ReplyKeyboardRemove())
            await show_settings_menu(message, state) # Все равно возвращаем в меню
    else:
        await message.answer("Ошибка подключения к БД.", reply_markup=ReplyKeyboardRemove())
        await state.clear(); await handle_today(message) # Выходим из настроек

@router.message(StateFilter(Settings.waiting_for_weight), F.text)
async def process_weight_input(message: Message, state: FSMContext):
    """Обрабатывает ввод веса."""
    user_id = message.from_user.id
    # Валидация ввода (разрешаем точку и запятую)
    try:
        weight_str = message.text.strip().replace(',', '.')
        weight = float(weight_str)
        if not (30.0 <= weight <= 300.0): # Простая проверка диапазона
            raise ValueError("Вес должен быть в разумных пределах (30-300 кг).")
    except (ValueError, AssertionError):
        await message.reply("Пожалуйста, введите вес числом от 30 до 300 кг (например, 75.5). Или /cancel")
        return # Остаемся в том же состоянии

    # Обновление в БД
    if db.db_pool:
        success = await db.update_user_profile_field(db.db_pool, user_id, "current_weight", weight)
        if success:
            logger.info(f"Вес для {user_id} установлен на {weight} кг. Пересчет нормы...")
            await recalculate_and_save_goal(user_id, state) # Пересчитываем норму
            await message.answer(f"✅ Вес обновлен!", reply_markup=ReplyKeyboardRemove())
            await show_settings_menu(message, state) # Возвращаемся в меню настроек
        else:
            await message.answer("Не удалось обновить вес. Попробуйте позже.", reply_markup=ReplyKeyboardRemove())
            await show_settings_menu(message, state)
    else:
        await message.answer("Ошибка подключения к БД.", reply_markup=ReplyKeyboardRemove())
        await state.clear(); await handle_today(message)

# --- Обработчик отмены для состояний ввода (рост, вес) ---
@router.message(
    Command("cancel"),
    StateFilter(Settings.waiting_for_height, Settings.waiting_for_weight)
)
@router.message(
    F.text == CANCEL_TEXT,
    StateFilter(Settings.waiting_for_height, Settings.waiting_for_weight)
)
async def cancel_settings_input_handler(message: Message, state: FSMContext):
    """Отменяет ввод параметра (рост/вес) и возвращает в меню настроек."""
    logger.info(f"Пользователь {message.from_user.id} отменил ввод параметра настроек.")
    await message.answer("Ввод отменен.", reply_markup=ReplyKeyboardRemove())
    # Возвращаемся к главному меню настроек
    await show_settings_menu(message, state)

# --- Логика для /timezone (если она нужна) ---
# (Оставлена без изменений)
@router.message(Command("timezone"), StateFilter(None))
async def handle_timezone_command(message: Message, state: FSMContext):
    user_id = message.from_user.id; logger.info(f"Пользователь {user_id} вызвал /timezone.")
    if not db.db_pool: await message.answer("Проблема с БД.", reply_markup=main_action_keyboard()); return
    current_tz = await db.get_user_timezone(db.db_pool, user_id)
    await message.answer(f"Ваш текущий пояс: <b>{current_tz}</b>\n\nВведите новый (напр., <code>Europe/Berlin</code>) или /cancel.\n<a href='{TIMEZONE_LIST_URL}'>Список поясов</a>", reply_markup=cancel_keyboard(), disable_web_page_preview=True)
    await state.set_state(Settings.waiting_for_timezone)
@router.message(StateFilter(Settings.waiting_for_timezone), F.text)
async def process_timezone_input(message: Message, state: FSMContext):
    user_id = message.from_user.id; timezone_input = message.text.strip()
    try: pytz.timezone(timezone_input); is_valid = True
    except Exception: is_valid = False
    if is_valid:
        logger.info(f"Пользователь {user_id} ввел валидный пояс: {timezone_input}")
        if db.db_pool:
            try: await db.update_user_timezone_db(db.db_pool, user_id, timezone_input); await message.answer(f"✅ Пояс установлен: <b>{timezone_input}</b>", reply_markup=main_action_keyboard()); await state.clear(); await handle_today(message)
            except Exception as e: logger.error(f"Ошибка обновления TZ в БД для {user_id}: {e}", exc_info=True); await message.answer("Ошибка сохранения. Попробуйте еще раз.", reply_markup=cancel_keyboard())
        else: logger.error("Пул БД не инициализирован при обновлении TZ."); await message.answer("Проблема с БД.", reply_markup=main_action_keyboard()); await state.clear()
    else: logger.warning(f"Пользователь {user_id} ввел невалидный пояс: {timezone_input}"); await message.reply(f"Некорректный пояс: <b>{escape(timezone_input)}</b>.\nИспользуйте формат из <a href='{TIMEZONE_LIST_URL}'>списка</a> или /cancel.", disable_web_page_preview=True, reply_markup=cancel_keyboard())
@router.message(Command("cancel"), StateFilter(Settings.waiting_for_timezone))
@router.message(F.text == CANCEL_TEXT, StateFilter(Settings.waiting_for_timezone))
async def cancel_timezone_handler(message: Message, state: FSMContext):
    logger.info(f"Пользователь {message.from_user.id} отменил установку часового пояса.")
    await state.clear(); await message.answer("Установка часового пояса отменена.", reply_markup=main_action_keyboard()); await handle_today(message)

