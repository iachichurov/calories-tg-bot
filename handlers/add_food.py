import logging
import asyncio
import aiohttp
import re
from typing import List, Dict, Any, Optional
from aiogram import Router, F, Bot
from aiogram.filters import Command, StateFilter
from aiogram.types import Message, ReplyKeyboardRemove, CallbackQuery
from aiogram.fsm.context import FSMContext
from html import escape

# Импортируем состояния, клавиатуры, функции БД и т.д.
from states import AddFood
from keyboards import (
    cancel_keyboard,
    request_calories_keyboard,
    main_action_keyboard,
    confirm_edit_keyboard,
    select_api_product_keyboard,
    product_suggestions_keyboard,
    FIND_CALORIES_TEXT,
    CANCEL_TEXT,
    ADD_PRODUCT_TEXT,
    CONFIRM_API_TEXT,
    EDIT_API_TEXT,
    MANUAL_INPUT_TEXT,
    PRODUCT_SELECT_CALLBACK_PREFIX
)
import database as db
from .reports import handle_today # Для показа сводки после действий

# Настройка логирования
logger = logging.getLogger(__name__)

# Создаем роутер для обработчиков этого модуля
router = Router()

# --- Константы ---
MAX_API_OPTIONS = 4 # Максимальное количество вариантов из API для показа пользователю
MIN_QUERY_LEN_FOR_SUGGEST = 2 # Минимальная длина ввода для показа инлайн-подсказок
API_TIMEOUT = 20 # Таймаут ожидания ответа от API в секундах
API_RETRY_ATTEMPTS = 3 # Количество попыток запроса к API
API_RETRY_DELAY = 2 # Задержка между попытками в секундах

# --- Функция для запроса к Open Food Facts API с повторными попытками ---
async def fetch_products_from_off(product_name: str) -> Optional[List[Dict[str, Any]]]:
    """
    Ищет продукты в Open Food Facts API с механизмом повторных попыток.
    Возвращает список словарей [{'name': str, 'calories': int}] или None.
    """
    # Нормализуем поисковый запрос (нижний регистр, замена ',', удаление %, лишние пробелы)
    search_term = product_name.lower().replace(',', '.').replace('%', '').strip()
    search_term = re.sub(r'\s+', ' ', search_term)
    if not search_term: # Если запрос пустой после нормализации
        logger.warning("Пустой поисковый запрос после нормализации.")
        return None

    # URL и параметры для запроса к API
    search_url = "https://world.openfoodfacts.org/cgi/search.pl"
    params = {
        "search_terms": search_term,
        "search_simple": 1,
        "action": "process",
        "json": 1,
        "fields": "product_name,nutriments", # Запрашиваем только нужные поля
        "page_size": MAX_API_OPTIONS + 1 # Запросим чуть больше на случай невалидных
    }
    # User-Agent важен для API, чтобы идентифицировать нашего бота
    headers = {'User-Agent': 'CalorieBot/1.0 (Telegram Bot; contact@example.com)'} # Замените на ваш контакт

    # Цикл повторных попыток
    last_exception = None
    for attempt in range(API_RETRY_ATTEMPTS):
        logger.info(f"Попытка {attempt + 1}/{API_RETRY_ATTEMPTS} запроса к OFF API для '{search_term}'...")
        try:
            # Создаем сессию aiohttp для выполнения запроса
            async with aiohttp.ClientSession(headers=headers) as session:
                async with session.get(search_url, params=params, timeout=API_TIMEOUT) as response:
                    response.raise_for_status() # Генерируем исключение для HTTP ошибок (4xx, 5xx)
                    data = await response.json() # Читаем ответ как JSON
                    logger.debug(f"Ответ OFF API (попытка {attempt + 1}): {data}") # Логируем сырой ответ

                    # Проверяем, есть ли продукты в ответе
                    if data.get("count", 0) > 0 and data.get("products"):
                        products_found = data["products"]
                        product_options = [] # Список для валидных вариантов
                        # Обрабатываем найденные продукты
                        for product in products_found:
                            # Ограничиваем количество опций
                            if len(product_options) >= MAX_API_OPTIONS: break

                            nutriments = product.get("nutriments", {})
                            product_name_found = product.get('product_name')
                            # Пропускаем продукты без имени
                            if not product_name_found: continue

                            logger.debug(f"Обработка продукта: {product_name_found}. Nutriments: {nutriments}")

                            calories_int: int | None = None
                            # 1. Пытаемся найти калории в ккал ('energy-kcal_100g')
                            calories_kcal = nutriments.get("energy-kcal_100g")
                            if calories_kcal:
                                try: calories_int = int(float(calories_kcal))
                                except (ValueError, TypeError): pass # Игнорируем ошибки конвертации

                            # 2. Если ккал не найдены, пытаемся найти энергию в кДж ('energy_100g') и пересчитать
                            if calories_int is None:
                                energy_kj = nutriments.get("energy_100g")
                                if energy_kj:
                                    try:
                                        unit = nutriments.get("energy_unit", "").lower()
                                        if unit == 'kcal': calories_int = int(float(energy_kj)) # Если вдруг тут ккал
                                        elif unit == 'kj' or not unit: calories_int = int(float(energy_kj) / 4.184) # Пересчет из кДж
                                    except (ValueError, TypeError): pass # Игнорируем ошибки конвертации

                            # Если калорийность найдена, добавляем продукт в опции
                            if calories_int is not None:
                                product_options.append({"name": product_name_found.strip(), "calories": calories_int})
                            else:
                                logger.info(f"OFF API: Не найдено данных о калорийности для '{product_name_found}', пропускаем.")

                        # Если собрали хотя бы один валидный вариант
                        if product_options:
                            logger.info(f"Запрос к OFF API успешен на попытке {attempt + 1}.")
                            return product_options # Возвращаем список вариантов

                    # Если API ответило, но продуктов нет или нет валидных
                    logger.info(f"OFF API не нашло валидных продуктов для '{search_term}' на попытке {attempt + 1}.")
                    return None # Считаем, что продукт не найден, выходим из retry

        # Ловим сетевые ошибки и таймауты для повторной попытки
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            last_exception = e
            logger.warning(f"Попытка {attempt + 1} не удалась для '{search_term}': {e}. Повтор через {API_RETRY_DELAY} сек...")
            if attempt < API_RETRY_ATTEMPTS - 1: # Если это не последняя попытка
                await asyncio.sleep(API_RETRY_DELAY) # Пауза перед следующей попыткой
            else:
                # Если все попытки исчерпаны
                logger.error(f"Все {API_RETRY_ATTEMPTS} попыток запроса к API для '{search_term}' не удались. Последняя ошибка: {e}")
                return None # Возвращаем None после всех неудачных попыток

        # Ловим другие неожиданные ошибки (не повторяем)
        except Exception as e:
            last_exception = e
            logger.error(f"Неожиданная ошибка при запросе к OFF API (попытка {attempt + 1}) для '{search_term}': {e}", exc_info=True)
            return None # Выходим из retry при неожиданной ошибке

    # Этот код не должен выполняться, но на всякий случай
    logger.error(f"Цикл Retry завершился неожиданно для '{search_term}'. Последнее исключение: {last_exception}")
    return None


# --- Обработчики состояний FSM ---

# Обработчик отмены (/cancel или текст) в любом состоянии AddFood
@router.message(Command("cancel"), StateFilter(AddFood))
@router.message(F.text == CANCEL_TEXT, StateFilter(AddFood))
async def cancel_add_food_handler(message: Message, state: FSMContext):
    """Отменяет текущий процесс добавления продукта."""
    current_state = await state.get_state()
    logger.info(f"Пользователь {message.from_user.id} отменил добавление продукта из состояния {current_state}.")
    # Пытаемся убрать инлайн-клавиатуру из предыдущего сообщения бота
    user_data = await state.get_data()
    last_bot_msg_id = user_data.get('last_bot_msg_id')
    if last_bot_msg_id:
        try:
            # Редактируем сообщение, убирая клавиатуру
            await message.bot.edit_message_reply_markup(
                chat_id=message.chat.id, message_id=last_bot_msg_id, reply_markup=None
            )
        except Exception as e:
            # Игнорируем ошибки (например, сообщение не найдено или уже без клавиатуры)
            logger.debug(f"Не удалось убрать инлайн-клавиатуру при отмене: {e}")
    await state.clear() # Очищаем состояние FSM
    await message.answer("Добавление продукта отменено.", reply_markup=main_action_keyboard()) # Возвращаем основную клавиатуру
    await handle_today(message) # Показываем сводку

# Запуск FSM добавления продукта (/add или кнопка)
@router.message(Command("add"), StateFilter(None)) # StateFilter(None) - только если не в состоянии
@router.message(F.text == ADD_PRODUCT_TEXT, StateFilter(None))
async def start_add_food(message: Message, state: FSMContext):
    """Начинает процесс добавления продукта."""
    user_id = message.from_user.id
    logger.info(f"Пользователь {user_id} начал добавление продукта.")
    # Отправляем сообщение с запросом имени и клавиатурой отмены
    bot_message = await message.answer("Введите название продукта:", reply_markup=cancel_keyboard())
    # Сохраняем ID сообщения бота (чтобы редактировать его с подсказками) и пустой ввод
    await state.update_data(last_bot_msg_id=bot_message.message_id, current_input="")
    # Устанавливаем первое состояние FSM
    await state.set_state(AddFood.waiting_for_product_name)


# Обработка текстового ввода в состоянии ожидания имени продукта
@router.message(StateFilter(AddFood.waiting_for_product_name), F.text)
async def process_product_name_input(message: Message, state: FSMContext, bot: Bot):
    """Обрабатывает ввод текста, ищет подсказки или переходит к следующему шагу."""
    product_name_input = message.text.strip()
    user_id = message.from_user.id
    user_data = await state.get_data()
    last_bot_msg_id = user_data.get('last_bot_msg_id')

    # Проверка на совпадение с текстом управляющих кнопок
    if product_name_input in [CANCEL_TEXT, FIND_CALORIES_TEXT, ADD_PRODUCT_TEXT, CONFIRM_API_TEXT, EDIT_API_TEXT, MANUAL_INPUT_TEXT]:
        await message.reply("Название продукта не должно совпадать с кнопками управления. Попробуйте еще раз или /cancel")
        return
    # Проверка на пустой ввод
    if not product_name_input: await message.reply("Название не может быть пустым. /cancel"); return
    # Проверка на длину (опционально)
    if len(product_name_input) > 250: await message.reply("Название слишком длинное. /cancel"); return

    logger.info(f"Пользователь {user_id} вводит: {product_name_input}")
    # Сохраняем текущий ввод в состояние
    await state.update_data(current_input=product_name_input)

    # --- Контекстный поиск по базе пользователя ---
    suggestions = []
    # Ищем подсказки, если введено достаточно символов и есть подключение к БД
    if len(product_name_input) >= MIN_QUERY_LEN_FOR_SUGGEST and db.db_pool:
        suggestions = await db.search_user_products(db.db_pool, user_id, product_name_input)

    # --- Логика в зависимости от наличия подсказок ---
    if suggestions:
        # Есть подсказки: редактируем сообщение бота, показываем инлайн-кнопки
        logger.info(f"Найдено {len(suggestions)} подсказок для '{product_name_input}'. Показываем.")
        inline_kb = product_suggestions_keyboard(suggestions)
        edit_text = "Введите название продукта (или выберите):"
        if last_bot_msg_id:
            try:
                # Пытаемся отредактировать предыдущее сообщение бота
                await bot.edit_message_text(
                    text=edit_text, chat_id=message.chat.id,
                    message_id=last_bot_msg_id, reply_markup=inline_kb
                )
            except Exception as e:
                # Если редактирование не удалось (например, сообщение старое)
                logger.warning(f"Не удалось отредактировать сообщение с подсказками: {e}")
                # Отправляем новое сообщение и обновляем его ID в состоянии
                bot_message = await message.answer(edit_text, reply_markup=inline_kb)
                await state.update_data(last_bot_msg_id=bot_message.message_id)
        else:
             # Если ID сообщения бота не было сохранено (маловероятно)
             bot_message = await message.answer(edit_text, reply_markup=inline_kb)
             await state.update_data(last_bot_msg_id=bot_message.message_id)
        # Остаемся в состоянии waiting_for_product_name, ждем выбора подсказки или нового ввода
    else:
        # --- Подсказок нет: Обрабатываем ввод как финальный ---
        logger.info(f"Подсказок нет, обрабатываем '{product_name_input}' как финальный ввод.")
        # Пытаемся убрать инлайн-клавиатуру из сообщения бота (если она там была)
        if last_bot_msg_id:
            try: await bot.edit_message_reply_markup(chat_id=message.chat.id, message_id=last_bot_msg_id, reply_markup=None)
            except Exception: pass # Игнорируем ошибки

        # Проверяем точное совпадение введенного имени в базе пользователя
        found_product = None
        if db.db_pool: found_product = await db.get_user_product(db.db_pool, user_id, product_name_input)

        if found_product:
            # Точное совпадение найдено: переходим к вводу веса
            found_name = found_product['product_name']; found_calories = found_product['calories_per_100g']
            # Обновляем состояние данными найденного продукта
            await state.update_data(product_name=found_name, calories_per_100g=found_calories, product_found=True, last_bot_msg_id=None) # Сбрасываем ID сообщения
            logger.info(f"Продукт '{found_name}' ({found_calories} ккал) найден (точное совпадение). Запрос веса.")
            # Отправляем НОВОЕ сообщение с запросом веса
            await message.answer(f"Продукт <b>{escape(found_name)}</b> найден.\nВведите вес в граммах:", reply_markup=cancel_keyboard())
            await state.set_state(AddFood.waiting_for_weight)
        else:
            # Точное совпадение не найдено: переходим к вводу веса (далее будет API/ручной ввод)
            # Обновляем состояние введенным пользователем именем
            await state.update_data(product_name=product_name_input, product_found=False, last_bot_msg_id=None) # Сбрасываем ID сообщения
            logger.info(f"Продукт '{product_name_input}' не найден (точное совпадение). Запрос веса.")
            # Отправляем НОВОЕ сообщение с запросом веса
            await message.answer("Продукт не найден в вашей базе. Введите вес в граммах:", reply_markup=cancel_keyboard())
            await state.set_state(AddFood.waiting_for_weight)


# Обработчик нажатия на инлайн-кнопку с подсказкой
@router.callback_query(StateFilter(AddFood.waiting_for_product_name), F.data.startswith(PRODUCT_SELECT_CALLBACK_PREFIX))
async def handle_product_suggestion_callback(callback: CallbackQuery, state: FSMContext):
    """Обрабатывает выбор продукта из инлайн-подсказок."""
    user_id = callback.from_user.id
    try:
        # Извлекаем ID продукта из callback_data
        selected_product_id = int(callback.data[len(PRODUCT_SELECT_CALLBACK_PREFIX):])
    except (ValueError, TypeError):
        logger.error(f"Ошибка извлечения product_id из callback_data: {callback.data}")
        await callback.answer("Ошибка данных кнопки.", show_alert=True)
        return

    logger.info(f"Пользователь {user_id} выбрал подсказку с ID: {selected_product_id}")

    # Получаем данные продукта из базы по ID
    found_product = None
    if db.db_pool:
        found_product = await db.get_user_product_by_id(db.db_pool, user_id, selected_product_id)

    if found_product:
        # Продукт найден в базе
        selected_product_name = found_product['product_name']
        found_calories = found_product['calories_per_100g']
        # Обновляем состояние данными выбранного продукта
        await state.update_data(
            product_name=selected_product_name, # Используем имя из базы
            calories_per_100g=found_calories,
            product_found=True,
            last_bot_msg_id=None # Сбрасываем ID сообщения с кнопками
        )
        logger.info(f"Подсказка ID={selected_product_id} ('{selected_product_name}', {found_calories} ккал) выбрана. Запрос веса.")
        # Убираем инлайн-клавиатуру из сообщения, на которое нажали
        try: await callback.message.edit_reply_markup(reply_markup=None)
        except Exception as e: logger.warning(f"Не удалось убрать инлайн-клавиатуру после выбора подсказки: {e}")
        # Отправляем НОВОЕ сообщение с запросом веса
        await callback.message.answer(
            f"Вы выбрали: <b>{escape(selected_product_name)}</b> ({found_calories} ккал/100г).\n"
            f"Введите вес в граммах:",
            reply_markup=cancel_keyboard()
        )
        # Переходим к состоянию ввода веса
        await state.set_state(AddFood.waiting_for_weight)
    else:
        # Если продукт по ID не найден (маловероятно, но возможно)
        logger.error(f"Ошибка: Выбранный по подсказке продукт ID={selected_product_id} не найден в базе для {user_id}.")
        await state.clear() # Сбрасываем состояние
        await callback.message.answer("Произошла ошибка при выборе продукта, попробуйте добавить заново.", reply_markup=main_action_keyboard())
        # Отвечаем на callback с сообщением об ошибке
        await callback.answer("Ошибка выбора продукта", show_alert=True)
        return # Выходим, чтобы не вызывать answer() еще раз

    await callback.answer() # Отвечаем на callback (убираем "часики")


# Обработка ввода веса
@router.message(StateFilter(AddFood.waiting_for_weight), F.text)
async def process_weight(message: Message, state: FSMContext):
    """Обрабатывает ввод веса и переходит к следующему шагу или завершает."""
    # Обработка отмены
    if message.text == CANCEL_TEXT: await cancel_add_food_handler(message, state); return
    # Валидация веса
    try: weight = int(message.text.strip()); assert weight > 0
    except (ValueError, AssertionError): await message.reply("Введите вес положительным числом (например, 150). Или /cancel"); return

    logger.info(f"Пользователь {message.from_user.id} ввел вес: {weight}")
    await state.update_data(weight=weight) # Сохраняем вес

    user_data = await state.get_data()
    product_found = user_data.get('product_found') # Был ли продукт найден в базе ранее?
    user_id = message.from_user.id

    if product_found:
        # Продукт был найден в базе -> Завершаем процесс
        product_name = user_data.get('product_name'); calories_100g = user_data.get('calories_per_100g')
        # Проверка целостности данных в состоянии
        if not all([product_name, isinstance(calories_100g, int), weight]):
            logger.error(f"Ошибка данных FSM (найденный продукт) для {user_id}. Сброс.")
            await state.clear(); await message.answer("Произошла ошибка...", reply_markup=main_action_keyboard()); return
        # Расчет калорий
        calories_consumed = round((calories_100g / 100) * weight)
        # Запись в БД
        if db.db_pool:
            try:
                await db.add_food_entry(db.db_pool, user_id, product_name, weight, calories_consumed)
                await message.answer(f"✅ Добавлено: {escape(product_name)} ({weight}г) - {calories_consumed} ккал.", reply_markup=main_action_keyboard())
                await state.clear(); await handle_today(message) # Очищаем состояние и показываем сводку
            except Exception as e:
                logger.error(f"Ошибка сохранения food_entry для {user_id}: {e}", exc_info=True)
                await message.answer("Ошибка сохранения.", reply_markup=main_action_keyboard()); await state.clear()
        else:
            # Если нет подключения к БД
            logger.warning("Пул БД не инициализирован при сохранении (найденный продукт).")
            await message.answer("Проблема с БД.", reply_markup=main_action_keyboard()); await state.clear()
    else:
        # Продукт НЕ был найден в базе -> Запрашиваем калории или поиск по API
        logger.info(f"Запрос калорийности/API для нового продукта {user_id}.")
        await message.answer(f"Введите калорийность на 100 грамм или нажмите '{FIND_CALORIES_TEXT}':", reply_markup=request_calories_keyboard())
        await state.set_state(AddFood.waiting_for_calories) # Переходим к следующему состоянию


# Обработка ввода калорий или запроса к API
@router.message(StateFilter(AddFood.waiting_for_calories), F.text)
async def process_calories_or_api(message: Message, state: FSMContext):
    """Обрабатывает ручной ввод калорий или запускает поиск по API."""
    user_id = message.from_user.id; user_input_text = message.text.strip()

    # Вариант 1: Нажата кнопка поиска по API
    if user_input_text == FIND_CALORIES_TEXT:
        logger.info(f"Пользователь {user_id} запросил поиск API.")
        user_data = await state.get_data(); product_name_original = user_data.get('product_name')
        # Проверка наличия имени продукта в состоянии
        if not product_name_original:
            logger.error(f"Ошибка имени продукта FSM (API) для {user_id}. Сброс.")
            await state.clear(); await message.answer("Произошла ошибка...", reply_markup=main_action_keyboard()); return
        # Сообщение о поиске и удаление Reply клавиатуры
        await message.answer(f"⏳ Ищу '{escape(product_name_original)}'...", reply_markup=ReplyKeyboardRemove())
        # Вызов функции API с Retry
        api_results = await fetch_products_from_off(product_name_original)

        if api_results:
            # API вернуло результаты
            if len(api_results) == 1:
                # Один результат -> Запрос подтверждения
                result = api_results[0]; api_calories = result['calories']; api_product_name = result['name']
                logger.info(f"API -> 1 результат: '{api_product_name}' ({api_calories} ккал). Запрос подтверждения.")
                await state.update_data(api_calories=api_calories, api_product_name=api_product_name)
                await message.answer(f"Я нашел: <b>{escape(api_product_name)}</b> ({api_calories} ккал/100г).\nИспользовать?", reply_markup=confirm_edit_keyboard())
                await state.set_state(AddFood.waiting_for_api_confirmation)
            else:
                # Несколько результатов -> Предлагаем выбор
                logger.info(f"API -> {len(api_results)} результатов. Предлагаем выбор.")
                await state.update_data(api_options=api_results)
                options_keyboard = select_api_product_keyboard(api_results)
                await message.answer("Я нашел несколько вариантов. Выберите:", reply_markup=options_keyboard)
                await state.set_state(AddFood.waiting_for_api_choice)
        else:
            # API ничего не нашло
            logger.info(f"API не нашло '{product_name_original}' после retries. Запрос ручного ввода.")
            await message.answer(f"Не удалось найти '{escape(product_name_original)}'.\nВведите калорийность вручную:", reply_markup=cancel_keyboard())
            await state.set_state(AddFood.waiting_for_calories) # Остаемся ждать ручного ввода
        return # Выход после обработки кнопки API

    # Вариант 2: Пользователь ввел текст (предполагаем ручной ввод калорий)
    try:
        calories_100g_manual = int(user_input_text); assert calories_100g_manual >= 0
    except (ValueError, AssertionError):
        # Некорректный ввод
        await message.reply(f"Введите число >= 0 или нажмите '{FIND_CALORIES_TEXT}'. Или /cancel"); return

    # Ручной ввод калорий успешен
    logger.info(f"Пользователь {user_id} ввел калорийность вручную: {calories_100g_manual}")
    user_data = await state.get_data(); product_name_original = user_data.get('product_name'); weight = user_data.get('weight')
    # Проверка данных состояния
    if not all([product_name_original, weight, isinstance(calories_100g_manual, int)]):
        logger.error(f"Ошибка данных FSM (ручной ввод) для {user_id}. Сброс.")
        await state.clear(); await message.answer("Произошла ошибка...", reply_markup=main_action_keyboard()); return
    # Расчет калорий порции
    calories_consumed = round((calories_100g_manual / 100) * weight)
    # Сохранение в БД
    if db.db_pool:
        try:
            normalized_product_name = await db.add_user_product(db.db_pool, user_id, product_name_original, calories_100g_manual)
            await db.add_food_entry(db.db_pool, user_id, normalized_product_name, weight, calories_consumed)
            await message.answer(f"✅ Добавлено: {escape(product_name_original)} ({weight}г) - {calories_consumed} ккал.", reply_markup=main_action_keyboard())
            await state.clear(); await handle_today(message) # Очистка состояния и показ сводки
        except Exception as e:
            logger.error(f"Ошибка сохранения БД (ручной ввод) для {user_id}: {e}", exc_info=True)
            await message.answer("Ошибка сохранения.", reply_markup=main_action_keyboard()); await state.clear()
    else:
        logger.warning("Пул БД не инициализирован при ручном вводе.")
        await message.answer("Проблема с БД.", reply_markup=main_action_keyboard()); await state.clear()


# Обработка выбора из нескольких вариантов API
@router.message(StateFilter(AddFood.waiting_for_api_choice), F.text)
async def process_api_choice(message: Message, state: FSMContext):
    """Обрабатывает выбор пользователя из предложенных API вариантов."""
    user_id = message.from_user.id; selected_option_text = message.text.strip()
    user_data = await state.get_data(); api_options = user_data.get('api_options')
    # Проверка наличия опций в состоянии
    if not api_options:
        logger.error(f"Ошибка опций API FSM для {user_id}. Сброс.")
        await state.clear(); await message.answer("Произошла ошибка...", reply_markup=main_action_keyboard()); return

    selected_product = None
    # Ищем выбранный продукт по тексту кнопки
    for option in api_options:
        button_text_part = f"{option['name'][:30]}... ({option['calories']} ккал)" if len(option['name']) > 30 else f"{option['name']} ({option['calories']} ккал)"
        if selected_option_text == button_text_part: selected_product = option; break
        button_text_full = f"{option['name']} ({option['calories']} ккал)"
        if selected_option_text == button_text_full: selected_product = option; break

    # Вариант 1: Выбран ручной ввод
    if selected_option_text == MANUAL_INPUT_TEXT:
        logger.info(f"Пользователь {user_id} выбрал ручной ввод после списка API.")
        await message.answer("Хорошо, введите калорийность на 100г:", reply_markup=cancel_keyboard())
        # Возвращаемся к состоянию ввода калорий, очищаем опции API
        await state.set_state(AddFood.waiting_for_calories); await state.update_data(api_options=None); return

    # Вариант 2: Выбран конкретный продукт
    if selected_product:
        selected_calories = selected_product['calories']; selected_name = selected_product['name']
        logger.info(f"Пользователь {user_id} выбрал вариант API: '{selected_name}' ({selected_calories} ккал). Запрос подтверждения.")
        # Сохраняем выбор в состояние, очищаем опции
        await state.update_data(api_calories=selected_calories, api_product_name=selected_name, api_options=None)
        # Переходим к подтверждению
        await message.answer(f"Вы выбрали: <b>{escape(selected_name)}</b> ({selected_calories} ккал/100г).\nИспользовать?", reply_markup=confirm_edit_keyboard())
        await state.set_state(AddFood.waiting_for_api_confirmation)
    else:
        # Ввод не соответствует ни одной кнопке
        logger.warning(f"Некорректный ввод '{selected_option_text}' в состоянии waiting_for_api_choice от {user_id}.")
        options_keyboard = select_api_product_keyboard(api_options)
        await message.reply("Пожалуйста, выберите один из предложенных вариантов.", reply_markup=options_keyboard)


# Обработка подтверждения/редактирования калорий из API
@router.message(StateFilter(AddFood.waiting_for_api_confirmation), F.text)
async def process_api_confirmation(message: Message, state: FSMContext):
    """Обрабатывает подтверждение ('Да') или запрос на изменение ('Изменить') калорийности из API."""
    user_id = message.from_user.id; user_input_text = message.text.strip()
    user_data = await state.get_data()
    # Используем имя из API, если оно есть, иначе - исходное
    product_name_to_save = user_data.get('api_product_name') or user_data.get('product_name')
    weight = user_data.get('weight'); api_calories = user_data.get('api_calories')
    # Проверка данных состояния
    if not all([product_name_to_save, weight, isinstance(api_calories, int)]):
        logger.error(f"Ошибка данных FSM (подтверждение API) для {user_id}. Сброс.")
        await state.clear(); await message.answer("Произошла ошибка...", reply_markup=main_action_keyboard()); return

    # Вариант 1: Пользователь подтвердил
    if user_input_text == CONFIRM_API_TEXT:
        logger.info(f"Пользователь {user_id} подтвердил API: {api_calories} для '{product_name_to_save}'")
        calories_consumed = round((api_calories / 100) * weight)
        # Сохранение в БД
        if db.db_pool:
            try:
                normalized_product_name = await db.add_user_product(db.db_pool, user_id, product_name_to_save, api_calories)
                await db.add_food_entry(db.db_pool, user_id, normalized_product_name, weight, calories_consumed)
                await message.answer(f"✅ Добавлено: {escape(product_name_to_save)} ({weight}г) - {calories_consumed} ккал (API).", reply_markup=main_action_keyboard())
                await state.clear(); await handle_today(message) # Очистка состояния и показ сводки
            except Exception as e:
                logger.error(f"Ошибка сохранения подтвержденных API для {user_id}: {e}", exc_info=True)
                await message.answer("Ошибка сохранения.", reply_markup=main_action_keyboard()); await state.clear()
        else:
            logger.warning("Пул БД не инициализирован при подтверждении API.")
            await message.answer("Проблема с БД.", reply_markup=main_action_keyboard()); await state.clear()

    # Вариант 2: Пользователь хочет изменить
    elif user_input_text == EDIT_API_TEXT:
        logger.info(f"Пользователь {user_id} решил изменить калорийность API для '{product_name_to_save}'.")
        await message.answer("Хорошо, введите свою калорийность на 100г:", reply_markup=cancel_keyboard())
        # Сохраняем имя продукта, которое редактируем, чтобы использовать его при ручном вводе
        await state.update_data(product_name=product_name_to_save)
        # Возвращаемся к состоянию ожидания ручного ввода калорий
        await state.set_state(AddFood.waiting_for_calories)

    # Вариант 3: Некорректный ввод
    else:
        logger.warning(f"Некорректный ввод '{user_input_text}' в состоянии waiting_for_api_confirmation от {user_id}.")
        await message.reply(f"Используйте кнопки: '{CONFIRM_API_TEXT}', '{EDIT_API_TEXT}' или '{CANCEL_TEXT}'.", reply_markup=confirm_edit_keyboard())

