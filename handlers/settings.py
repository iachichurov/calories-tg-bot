import logging
import pytz
from html import escape
from aiogram import Router, F, Bot
from aiogram.filters import Command, StateFilter
from aiogram.types import Message, ReplyKeyboardRemove, CallbackQuery # Добавили CallbackQuery
from aiogram.fsm.context import FSMContext
from contextlib import suppress # Для подавления ошибок при удалении сообщений
from aiogram.exceptions import TelegramBadRequest # Для обработки ошибок API

# Импортируем состояния, клавиатуры, функции БД, утилиты
from states import Settings
from keyboards import (
    cancel_keyboard, main_action_keyboard, settings_main_keyboard,
    select_goal_keyboard, select_gender_keyboard,
    SETTINGS_ACTION_CALLBACK_PREFIX, GENDER_SELECT_CALLBACK_PREFIX,
    GOAL_SELECT_CALLBACK_PREFIX, CANCEL_TEXT
)
import database as db
import utils # Наш модуль с расчетами
from .reports import handle_today # Для показа сводки после

logger = logging.getLogger(__name__)

# Создаем роутер для настроек
router = Router()

# --- Вспомогательная функция для пересчета и сохранения нормы ---
async def recalculate_and_save_goal(user_id: int, state: FSMContext):
    """Получает данные профиля, пересчитывает норму и сохраняет в БД."""
    if not db.db_pool:
        logger.error(f"Нет подключения к БД для пересчета нормы {user_id}")
        return None # Возвращаем None в случае ошибки БД

    profile_data = await db.get_user_profile_data(db.db_pool, user_id)
    if not profile_data:
        logger.warning(f"Нет данных профиля для пересчета нормы {user_id}")
        await db.update_user_daily_goal(db.db_pool, user_id, None) # Сбрасываем норму
        return None

    weight = profile_data.get('current_weight')
    height = profile_data.get('height')
    gender = profile_data.get('gender')
    goal = profile_data.get('goal')

    # Проверяем наличие всех необходимых данных
    if not all([weight, height, gender, goal]):
        logger.info(f"Не все данные профиля заполнены для {user_id}. Норма не рассчитана.")
        await db.update_user_daily_goal(db.db_pool, user_id, None) # Сбрасываем норму
        return None

    # Рассчитываем LBM
    lbm = utils.calculate_lbm(weight_kg=float(weight), height_cm=height, gender=gender)
    if lbm is None:
        logger.warning(f"Не удалось рассчитать LBM для {user_id}. Норма не рассчитана.")
        await db.update_user_daily_goal(db.db_pool, user_id, None) # Сбрасываем норму
        return None

    # Рассчитываем калории
    _, calories = utils.calculate_target_macros_and_calories(lbm=lbm, goal=goal) or (None, None)
    if calories is None:
        logger.warning(f"Не удалось рассчитать калории для {user_id}. Норма не рассчитана.")
        await db.update_user_daily_goal(db.db_pool, user_id, None) # Сбрасываем норму
        return None

    # Сохраняем рассчитанную норму в БД
    await db.update_user_daily_goal(db.db_pool, user_id, calories)
    logger.info(f"Норма калорий для {user_id} пересчитана и сохранена: {calories} ккал.")
    return calories # Возвращаем рассчитанную норму


# --- Отображение текущих настроек ---
async def show_settings_menu(message: Message, state: FSMContext, user_id: int):
    """Отображает текущие настройки и главное меню настроек."""
    profile_data = None
    current_goal_text = "Не установлена"
    current_gender_text = "Не указан"
    current_height_text = "Не указан"
    current_weight_text = "Не указан"
    current_norm_text = "Не рассчитана (заполните профиль)"

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
            if weight: current_weight_text = f"{weight} кг"

            # Получаем рассчитанную норму из базы
            norm = profile_data.get('daily_calorie_goal') # Используем данные из профиля, если они есть
            if norm is None: # Если нормы нет, пробуем пересчитать
                 norm = await recalculate_and_save_goal(user_id, state) # Пересчитываем норму

            if norm:
                current_norm_text = f"~{norm} ккал/день"


    settings_text = (
        f"⚙️ **Настройки профиля:**\n\n"
        f"🎯 Ваша цель: <b>{current_goal_text}</b>\n"
        f"🧍 Ваш пол: <b>{current_gender_text}</b>\n"
        f"📏 Ваш рост: <b>{current_height_text}</b>\n"
        f"⚖️ Ваш вес: <b>{current_weight_text}</b>\n\n"
        f"📊 Расчетная норма: <b>{current_norm_text}</b>\n\n"
        f"Выберите, что хотите изменить:"
    )

    # Отправляем сообщение с инлайн-клавиатурой
    await message.answer(settings_text, reply_markup=settings_main_keyboard())
    await state.set_state(Settings.waiting_for_action) # Устанавливаем состояние ожидания действия


# --- Обработчики команды /settings и /setweight ---

@router.message(Command("settings"), StateFilter(None))
async def handle_settings_command(message: Message, state: FSMContext):
    """Отображает меню настроек профиля."""
    user_id = message.from_user.id
    logger.info(f"Пользователь {user_id} вызвал команду /settings.")
    await show_settings_menu(message, state, user_id)

@router.message(Command("setweight"), StateFilter(None))
async def handle_setweight_command(message: Message, state: FSMContext):
    """Начинает процесс установки веса."""
    user_id = message.from_user.id
    logger.info(f"Пользователь {user_id} вызвал команду /setweight.")
    await message.answer("Введите ваш текущий вес в килограммах (например, 75.5):", reply_markup=cancel_keyboard())
    await state.set_state(Settings.waiting_for_weight)

# --- Обработчики CallbackQuery для меню настроек ---

@router.callback_query(F.data.startswith(SETTINGS_ACTION_CALLBACK_PREFIX))
async def handle_settings_action(callback: CallbackQuery, state: FSMContext):
    """Обрабатывает нажатия кнопок в главном меню настроек."""
    action = callback.data.split(":")[1]
    user_id = callback.from_user.id
    message = callback.message

    # Убираем предыдущую инлайн-клавиатуру
    with suppress(TelegramBadRequest): # Подавляем ошибку, если сообщение уже без клавиатуры
        await message.edit_reply_markup(reply_markup=None)

    if action == "change_goal":
        logger.info(f"Пользователь {user_id} выбрал изменить цель.")
        await message.answer("Выберите вашу основную цель:", reply_markup=select_goal_keyboard())
        # Остаемся в состоянии waiting_for_action или можно перейти в новое? Пока оставим так.
        await state.set_state(Settings.waiting_for_action) # Ждем нажатия кнопки цели

    elif action == "change_gender":
        logger.info(f"Пользователь {user_id} выбрал изменить пол.")
        await message.answer("Выберите ваш пол:", reply_markup=select_gender_keyboard())
        await state.set_state(Settings.waiting_for_action) # Ждем нажатия кнопки пола

    elif action == "change_height":
        logger.info(f"Пользователь {user_id} выбрал изменить рост.")
        await message.answer("Введите ваш рост в сантиметрах (например, 180):", reply_markup=cancel_keyboard())
        await state.set_state(Settings.waiting_for_height)

    elif action == "change_weight":
        logger.info(f"Пользователь {user_id} выбрал изменить вес.")
        await message.answer("Введите ваш текущий вес в килограммах (например, 75.5):", reply_markup=cancel_keyboard())
        await state.set_state(Settings.waiting_for_weight)

    # elif action == "change_timezone":
        # Логика для изменения таймзоны (если нужно вернуть)

    elif action == "back":
        logger.info(f"Пользователь {user_id} нажал 'Назад' в настройках.")
        await state.clear() # Выходим из состояний настроек
        await message.answer("Настройки закрыты.", reply_markup=main_action_keyboard())
        await handle_today(message) # Показываем сводку

    await callback.answer() # Отвечаем на callback

# --- Обработчики CallbackQuery для выбора цели и пола ---

@router.callback_query(F.data.startswith(GOAL_SELECT_CALLBACK_PREFIX), StateFilter(Settings.waiting_for_action))
async def handle_goal_selection(callback: CallbackQuery, state: FSMContext):
    """Обрабатывает выбор цели."""
    goal = callback.data.split(":")[1]
    user_id = callback.from_user.id
    message = callback.message

    # Убираем клавиатуру выбора цели
    with suppress(TelegramBadRequest):
        await message.edit_reply_markup(reply_markup=None)

    goal_to_save = goal if goal != "none" else None # Сохраняем NULL, если выбрано "Не устанавливать"
    goal_text = goal # Для лога

    if db.db_pool:
        success = await db.update_user_profile_field(db.db_pool, user_id, "goal", goal_to_save)
        if success:
            logger.info(f"Цель для {user_id} установлена на '{goal_text}'. Пересчет нормы...")
            await recalculate_and_save_goal(user_id, state) # Пересчитываем норму
            await message.answer(f"✅ Цель обновлена!")
            await show_settings_menu(message, state, user_id) # Показываем обновленное меню настроек
        else:
            await message.answer("Не удалось обновить цель. Попробуйте позже.")
            await show_settings_menu(message, state, user_id) # Возвращаем в меню
    else:
        await message.answer("Ошибка подключения к БД.")
        await state.clear(); await handle_today(message) # Выходим из настроек

    await callback.answer()

@router.callback_query(F.data.startswith(GENDER_SELECT_CALLBACK_PREFIX), StateFilter(Settings.waiting_for_action))
async def handle_gender_selection(callback: CallbackQuery, state: FSMContext):
    """Обрабатывает выбор пола."""
    gender = callback.data.split(":")[1]
    user_id = callback.from_user.id
    message = callback.message

    with suppress(TelegramBadRequest):
        await message.edit_reply_markup(reply_markup=None)

    if db.db_pool:
        success = await db.update_user_profile_field(db.db_pool, user_id, "gender", gender)
        if success:
            logger.info(f"Пол для {user_id} установлен на '{gender}'. Пересчет нормы...")
            await recalculate_and_save_goal(user_id, state)
            await message.answer(f"✅ Пол обновлен!")
            await show_settings_menu(message, state, user_id)
        else:
            await message.answer("Не удалось обновить пол. Попробуйте позже.")
            await show_settings_menu(message, state, user_id)
    else:
        await message.answer("Ошибка подключения к БД.")
        await state.clear(); await handle_today(message)

    await callback.answer()

# --- Обработчики ввода роста и веса ---

@router.message(StateFilter(Settings.waiting_for_height), F.text)
async def process_height_input(message: Message, state: FSMContext):
    """Обрабатывает ввод роста."""
    user_id = message.from_user.id
    try:
        height = int(message.text.strip())
        if not (100 < height < 250): # Простая валидация диапазона
            raise ValueError("Рост должен быть в разумных пределах (100-250 см).")
    except ValueError:
        await message.reply("Пожалуйста, введите рост целым числом в сантиметрах (например, 175). Или /cancel")
        return

    if db.db_pool:
        success = await db.update_user_profile_field(db.db_pool, user_id, "height", height)
        if success:
            logger.info(f"Рост для {user_id} установлен на {height} см. Пересчет нормы...")
            await recalculate_and_save_goal(user_id, state)
            await message.answer(f"✅ Рост обновлен!", reply_markup=ReplyKeyboardRemove()) # Убираем cancel keyboard
            await show_settings_menu(message, state, user_id) # Возвращаемся в меню настроек
        else:
            await message.answer("Не удалось обновить рост. Попробуйте позже.", reply_markup=ReplyKeyboardRemove())
            await show_settings_menu(message, state, user_id)
    else:
        await message.answer("Ошибка подключения к БД.", reply_markup=ReplyKeyboardRemove())
        await state.clear(); await handle_today(message)


@router.message(StateFilter(Settings.waiting_for_weight), F.text)
async def process_weight_input(message: Message, state: FSMContext):
    """Обрабатывает ввод веса."""
    user_id = message.from_user.id
    try:
        # Разрешаем ввод через точку или запятую, заменяем запятую на точку
        weight_str = message.text.strip().replace(',', '.')
        weight = float(weight_str)
        if not (30 < weight < 300): # Простая валидация диапазона
            raise ValueError("Вес должен быть в разумных пределах (30-300 кг).")
    except ValueError:
        await message.reply("Пожалуйста, введите вес числом (например, 75.5 или 75). Или /cancel")
        return

    if db.db_pool:
        success = await db.update_user_profile_field(db.db_pool, user_id, "current_weight", weight)
        if success:
            logger.info(f"Вес для {user_id} установлен на {weight} кг. Пересчет нормы...")
            await recalculate_and_save_goal(user_id, state)
            await message.answer(f"✅ Вес обновлен!", reply_markup=ReplyKeyboardRemove())
            await show_settings_menu(message, state, user_id) # Возвращаемся в меню настроек
        else:
            await message.answer("Не удалось обновить вес. Попробуйте позже.", reply_markup=ReplyKeyboardRemove())
            await show_settings_menu(message, state, user_id)
    else:
        await message.answer("Ошибка подключения к БД.", reply_markup=ReplyKeyboardRemove())
        await state.clear(); await handle_today(message)

# --- Обработчик отмены для состояний настроек (дублирует общий, но нужен для StateFilter) ---
# Можно объединить с общим cancel_handler, если вынести логику удаления инлайн клавиатуры
@router.message(Command("cancel"), StateFilter(Settings))
@router.message(F.text == CANCEL_TEXT, StateFilter(Settings))
async def cancel_settings_input_handler(message: Message, state: FSMContext):
    """Отменяет ввод конкретного параметра настроек."""
    logger.info(f"Пользователь {message.from_user.id} отменил ввод параметра настроек.")
    await message.answer("Ввод отменен.", reply_markup=ReplyKeyboardRemove())
    # Возвращаемся к главному меню настроек
    await show_settings_menu(message, state, message.from_user.id)

