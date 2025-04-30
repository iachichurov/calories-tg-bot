import logging
import pytz # Для валидации таймзоны, если оставим
from html import escape
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
    GOAL_SELECT_CALLBACK_PREFIX, CANCEL_TEXT
)
import database as db
import utils # Наш новый модуль с расчетами LBM и калорий
from .reports import handle_today # Для показа сводки после обновления настроек

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
    сохраняет рассчитанную норму (daily_calorie_goal) в БД.
    Возвращает рассчитанную норму калорий или None, если расчет не удался.
    """
    # Проверяем подключение к БД
    if not db.db_pool:
        logger.error(f"Нет подключения к БД для пересчета нормы {user_id}")
        return None

    # Получаем все необходимые данные профиля из БД
    profile_data = await db.get_user_profile_data(db.db_pool, user_id)
    if not profile_data:
        # Если профиля нет (маловероятно, т.к. пользователь создается), сбрасываем норму
        logger.warning(f"Нет данных профиля для пересчета нормы {user_id}")
        await db.update_user_daily_goal(db.db_pool, user_id, None)
        return None

    # Извлекаем нужные поля
    weight = profile_data.get('current_weight')
    height = profile_data.get('height')
    gender = profile_data.get('gender')
    goal = profile_data.get('goal') # Цель пользователя

    # Проверяем, что все данные для расчета LBM и цели установлены
    if not all([weight, height, gender]):
        logger.info(f"Не все данные профиля (вес/рост/пол) заполнены для {user_id}. Норма не рассчитана.")
        await db.update_user_daily_goal(db.db_pool, user_id, None) # Сбрасываем норму
        return None
    if not goal: # Цель тоже нужна для расчета калорий по БЖУ
        logger.info(f"Цель не установлена для {user_id}. Норма не рассчитана.")
        await db.update_user_daily_goal(db.db_pool, user_id, None) # Сбрасываем норму
        return None

    # 1. Рассчитываем LBM
    lbm = utils.calculate_lbm(weight_kg=float(weight), height_cm=height, gender=gender)
    if lbm is None:
        # Если LBM не рассчитался (например, неверный пол или неправдоподобные значения)
        logger.warning(f"Не удалось рассчитать LBM для {user_id}. Норма не рассчитана.")
        await db.update_user_daily_goal(db.db_pool, user_id, None) # Сбрасываем норму
        return None

    # 2. Рассчитываем калории на основе LBM и цели
    _, calories = utils.calculate_target_macros_and_calories(lbm=lbm, goal=goal) or (None, None)
    if calories is None:
        # Если калории не рассчитались
        logger.warning(f"Не удалось рассчитать калории для {user_id}. Норма не рассчитана.")
        await db.update_user_daily_goal(db.db_pool, user_id, None) # Сбрасываем норму
        return None

    # 3. Сохраняем рассчитанную норму калорий в БД
    await db.update_user_daily_goal(db.db_pool, user_id, calories)
    logger.info(f"Норма калорий для {user_id} пересчитана и сохранена: {calories} ккал.")
    # Возвращаем рассчитанную норму
    return calories


# --- Функция для отображения главного меню настроек ---
async def show_settings_menu(message_or_callback: Message | CallbackQuery, state: FSMContext):
    """
    Отображает текущие настройки профиля и инлайн-клавиатуру
    с кнопками для их изменения.
    Может вызываться как из Message, так и из CallbackQuery.
    """
    user_id = message_or_callback.from_user.id
    # Определяем, как отвечать (новым сообщением или редактированием)
    if isinstance(message_or_callback, Message):
        answer_method = message_or_callback.answer
    else: # CallbackQuery
        answer_method = message_or_callback.message.answer
        # Отвечаем на callback, чтобы убрать часики
        await message_or_callback.answer()

    # Получаем текущие данные профиля
    profile_data = None
    current_goal_text = "Не установлена"
    current_gender_text = "Не указан"
    current_height_text = "Не указан"
    current_weight_text = "Не указан"
    current_norm_text = "Не рассчитана" # По умолчанию

    if db.db_pool:
        profile_data = await db.get_user_profile_data(db.db_pool, user_id)
        if profile_data:
            # Форматируем цель
            goal = profile_data.get('goal')
            if goal == 'deficit': current_goal_text = "📉 Дефицит"
            elif goal == 'maintenance': current_goal_text = "維持 Поддержание"
            elif goal == 'surplus': current_goal_text = "📈 Профицит"
            # Форматируем пол
            gender = profile_data.get('gender')
            if gender == 'male': current_gender_text = "👨 Мужской"
            elif gender == 'female': current_gender_text = "👩 Женский"
            # Форматируем рост
            height = profile_data.get('height')
            if height: current_height_text = f"{height} см"
            # Форматируем вес
            weight = profile_data.get('current_weight')
            if weight: current_weight_text = f"{weight:.1f} кг" # С одним знаком после запятой

            # Получаем рассчитанную норму из базы (она должна быть актуальной)
            norm = profile_data.get('daily_calorie_goal')
            if norm:
                current_norm_text = f"~<b>{norm}</b> ккал/день"
            else:
                # Если нормы нет, но есть все данные, пробуем пересчитать
                if all([weight, height, gender, goal]):
                     norm = await recalculate_and_save_goal(user_id, state)
                     if norm: current_norm_text = f"~<b>{norm}</b> ккал/день"
                     else: current_norm_text = "Ошибка расчета"
                else:
                     current_norm_text = "Не рассчитана (заполните профиль)"


    # Собираем текст сообщения с текущими настройками
    settings_text = (
        f"⚙️ **Настройки профиля:**\n\n"
        f"🎯 Ваша цель: <b>{current_goal_text}</b>\n"
        f"🧍 Ваш пол: <b>{current_gender_text}</b>\n"
        f"📏 Ваш рост: <b>{current_height_text}</b>\n"
        f"⚖️ Ваш вес: <b>{current_weight_text}</b>\n\n"
        f"📊 Расчетная норма: {current_norm_text}\n\n" # Убрали жирный шрифт у заголовка нормы
        f"Выберите, что хотите изменить:"
    )

    # Отправляем/редактируем сообщение с инлайн-клавиатурой
    # Пробуем редактировать, если это был callback
    if isinstance(message_or_callback, CallbackQuery):
         with suppress(TelegramBadRequest): # Игнорируем ошибку, если сообщение не изменилось
              await message_or_callback.message.edit_text(settings_text, reply_markup=settings_main_keyboard())
              await state.set_state(Settings.waiting_for_action) # Устанавливаем состояние ожидания действия
              return # Выходим после редактирования

    # Если это было сообщение или редактирование не удалось, отправляем новое
    await answer_method(settings_text, reply_markup=settings_main_keyboard())
    await state.set_state(Settings.waiting_for_action) # Устанавливаем состояние ожидания действия


# --- Обработчики команды /settings и /setweight ---

@router.message(Command("settings"), StateFilter(None)) # Только если не в другом состоянии
async def handle_settings_command(message: Message, state: FSMContext):
    """Отображает меню настроек профиля по команде /settings."""
    user_id = message.from_user.id
    logger.info(f"Пользователь {user_id} вызвал команду /settings.")
    # Показываем меню настроек
    await show_settings_menu(message, state)

@router.message(Command("setweight"), StateFilter(None)) # Только если не в другом состоянии
async def handle_setweight_command(message: Message, state: FSMContext):
    """Начинает процесс установки веса по команде /setweight."""
    user_id = message.from_user.id
    logger.info(f"Пользователь {user_id} вызвал команду /setweight.")
    # Спрашиваем вес и показываем клавиатуру отмены
    await message.answer("Введите ваш текущий вес в килограммах (например, 75.5):", reply_markup=cancel_keyboard())
    # Устанавливаем состояние ожидания веса
    await state.set_state(Settings.waiting_for_weight)

# --- Обработчики CallbackQuery для основного меню настроек ---

@router.callback_query(F.data.startswith(SETTINGS_ACTION_CALLBACK_PREFIX), StateFilter(Settings.waiting_for_action))
async def handle_settings_action(callback: CallbackQuery, state: FSMContext):
    """Обрабатывает нажатия кнопок в главном меню настроек."""
    action = callback.data.split(":")[1] # Получаем действие из callback_data (например, 'change_goal')
    user_id = callback.from_user.id
    message = callback.message # Сообщение, к которому прикреплены кнопки

    # Убираем предыдущую инлайн-клавиатуру из сообщения
    with suppress(TelegramBadRequest):
        await message.edit_reply_markup(reply_markup=None)

    # Выполняем действие в зависимости от нажатой кнопки
    if action == "change_goal":
        logger.info(f"Пользователь {user_id} выбрал изменить цель.")
        # Показываем клавиатуру выбора цели
        await message.answer("Выберите вашу основную цель:", reply_markup=select_goal_keyboard())
        # Остаемся в состоянии ожидания действия (нажатия кнопки цели)
        await state.set_state(Settings.waiting_for_action)

    elif action == "change_gender":
        logger.info(f"Пользователь {user_id} выбрал изменить пол.")
        # Показываем клавиатуру выбора пола
        await message.answer("Выберите ваш пол:", reply_markup=select_gender_keyboard())
        await state.set_state(Settings.waiting_for_action) # Ждем нажатия кнопки пола

    elif action == "change_height":
        logger.info(f"Пользователь {user_id} выбрал изменить рост.")
        # Запрашиваем ввод роста текстом и показываем кнопку отмены
        await message.answer("Введите ваш рост в сантиметрах (например, 180):", reply_markup=cancel_keyboard())
        # Переходим в состояние ожидания ввода роста
        await state.set_state(Settings.waiting_for_height)

    elif action == "change_weight":
        logger.info(f"Пользователь {user_id} выбрал изменить вес.")
        # Запрашиваем ввод веса текстом
        await message.answer("Введите ваш текущий вес в килограммах (например, 75.5):", reply_markup=cancel_keyboard())
        await state.set_state(Settings.waiting_for_weight)

    # elif action == "change_timezone":
        # Можно добавить логику для изменения таймзоны здесь, если нужно

    elif action == "back":
        # Пользователь нажал "Назад"
        logger.info(f"Пользователь {user_id} нажал 'Назад' в настройках.")
        await state.clear() # Выходим из состояний настроек
        await message.answer("Настройки закрыты.", reply_markup=main_action_keyboard()) # Показываем основную клавиатуру
        await handle_today(message) # Показываем сводку

    await callback.answer() # Отвечаем на callback, чтобы убрать "часики"


# --- Обработчики CallbackQuery для выбора цели и пола ---

@router.callback_query(F.data.startswith(GOAL_SELECT_CALLBACK_PREFIX), StateFilter(Settings.waiting_for_action))
async def handle_goal_selection(callback: CallbackQuery, state: FSMContext):
    """Обрабатывает выбор цели из инлайн-кнопок."""
    goal = callback.data.split(":")[1] # Получаем выбранную цель ('deficit', 'none' и т.д.)
    user_id = callback.from_user.id
    message = callback.message

    # Убираем клавиатуру выбора цели
    with suppress(TelegramBadRequest):
        await message.edit_reply_markup(reply_markup=None)

    # Сохраняем NULL в базу, если выбрано "Не устанавливать"
    goal_to_save = goal if goal != "none" else None
    goal_text = goal # Используем исходное значение для лога

    if db.db_pool:
        # Обновляем поле 'goal' в базе
        success = await db.update_user_profile_field(db.db_pool, user_id, "goal", goal_to_save)
        if success:
            logger.info(f"Цель для {user_id} установлена на '{goal_text}'. Пересчет нормы...")
            # Пересчитываем и сохраняем норму калорий
            await recalculate_and_save_goal(user_id, state)
            await message.answer(f"✅ Цель обновлена!")
            # Показываем обновленное меню настроек
            await show_settings_menu(callback, state) # Передаем callback, чтобы функция знала, как ответить
        else:
            # Если не удалось обновить в БД
            await message.answer("Не удалось обновить цель. Попробуйте позже.")
            await show_settings_menu(callback, state) # Возвращаем в меню
    else:
        # Если нет подключения к БД
        await message.answer("Ошибка подключения к БД.")
        await state.clear(); await handle_today(message) # Выходим из настроек

    await callback.answer() # Отвечаем на callback

@router.callback_query(F.data.startswith(GENDER_SELECT_CALLBACK_PREFIX), StateFilter(Settings.waiting_for_action))
async def handle_gender_selection(callback: CallbackQuery, state: FSMContext):
    """Обрабатывает выбор пола из инлайн-кнопок."""
    gender = callback.data.split(":")[1] # 'male' или 'female'
    user_id = callback.from_user.id
    message = callback.message

    # Убираем клавиатуру выбора пола
    with suppress(TelegramBadRequest):
        await message.edit_reply_markup(reply_markup=None)

    if db.db_pool:
        # Обновляем поле 'gender'
        success = await db.update_user_profile_field(db.db_pool, user_id, "gender", gender)
        if success:
            logger.info(f"Пол для {user_id} установлен на '{gender}'. Пересчет нормы...")
            # Пересчитываем норму
            await recalculate_and_save_goal(user_id, state)
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
    # Валидация введенного значения
    try:
        height = int(message.text.strip())
        if not (100 <= height <= 250): # Простая проверка диапазона
            raise ValueError("Рост должен быть в разумных пределах (100-250 см).")
    except ValueError:
        # Если ввод некорректный, просим ввести снова
        await message.reply("Пожалуйста, введите рост целым числом в сантиметрах (например, 175). Или /cancel")
        return # Остаемся в том же состоянии

    # Если ввод корректный, обновляем в БД
    if db.db_pool:
        success = await db.update_user_profile_field(db.db_pool, user_id, "height", height)
        if success:
            logger.info(f"Рост для {user_id} установлен на {height} см. Пересчет нормы...")
            # Пересчитываем норму
            await recalculate_and_save_goal(user_id, state)
            await message.answer(f"✅ Рост обновлен!", reply_markup=ReplyKeyboardRemove()) # Убираем cancel keyboard
            # Возвращаемся в главное меню настроек
            await show_settings_menu(message, state)
        else:
            # Если ошибка обновления БД
            await message.answer("Не удалось обновить рост. Попробуйте позже.", reply_markup=ReplyKeyboardRemove())
            await show_settings_menu(message, state) # Все равно возвращаем в меню
    else:
        # Если нет подключения к БД
        await message.answer("Ошибка подключения к БД.", reply_markup=ReplyKeyboardRemove())
        await state.clear(); await handle_today(message) # Выходим из настроек


@router.message(StateFilter(Settings.waiting_for_weight), F.text)
async def process_weight_input(message: Message, state: FSMContext):
    """Обрабатывает ввод веса."""
    user_id = message.from_user.id
    # Валидация введенного значения (разрешаем точку и запятую)
    try:
        weight_str = message.text.strip().replace(',', '.')
        weight = float(weight_str)
        if not (30.0 <= weight <= 300.0): # Простая проверка диапазона
            raise ValueError("Вес должен быть в разумных пределах (30-300 кг).")
    except ValueError:
        await message.reply("Пожалуйста, введите вес числом (например, 75.5 или 75). Или /cancel")
        return # Остаемся в том же состоянии

    # Если ввод корректный, обновляем в БД
    if db.db_pool:
        success = await db.update_user_profile_field(db.db_pool, user_id, "current_weight", weight)
        if success:
            logger.info(f"Вес для {user_id} установлен на {weight} кг. Пересчет нормы...")
            # Пересчитываем норму
            await recalculate_and_save_goal(user_id, state)
            await message.answer(f"✅ Вес обновлен!", reply_markup=ReplyKeyboardRemove())
             # Возвращаемся в главное меню настроек
            await show_settings_menu(message, state)
        else:
            await message.answer("Не удалось обновить вес. Попробуйте позже.", reply_markup=ReplyKeyboardRemove())
            await show_settings_menu(message, state)
    else:
        await message.answer("Ошибка подключения к БД.", reply_markup=ReplyKeyboardRemove())
        await state.clear(); await handle_today(message)

# --- Обработчик отмены для состояний ввода (рост, вес) ---
# Можно было бы объединить с общим cancel_handler, если вынести логику show_settings_menu
@router.message(Command("cancel"), StateFilter(Settings.waiting_for_height, Settings.waiting_for_weight))
@router.message(F.text == CANCEL_TEXT, StateFilter(Settings.waiting_for_height, Settings.waiting_for_weight))
async def cancel_settings_input_handler(message: Message, state: FSMContext):
    """Отменяет ввод конкретного параметра (рост/вес) и возвращает в меню настроек."""
    logger.info(f"Пользователь {message.from_user.id} отменил ввод параметра настроек.")
    await message.answer("Ввод отменен.", reply_markup=ReplyKeyboardRemove())
    # Возвращаемся к главному меню настроек
    await show_settings_menu(message, state)

