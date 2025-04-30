import logging
import pytz # Для проверки валидности таймзоны
from aiogram import Router, F, Bot
from aiogram.filters import Command, StateFilter
from aiogram.types import Message, ReplyKeyboardRemove
from aiogram.fsm.context import FSMContext
from html import escape

# Импортируем состояния, клавиатуры, функции БД
from states import Settings
from keyboards import cancel_keyboard, main_action_keyboard, CANCEL_TEXT
import database as db
from .reports import handle_today # Для показа сводки после установки

logger = logging.getLogger(__name__)

# Создаем роутер для настроек
router = Router()

# Ссылка на список часовых поясов (TZ Database names)
# Можно использовать любую актуальную ссылку
TIMEZONE_LIST_URL = "https://en.wikipedia.org/wiki/List_of_tz_database_time_zones"

# Обработчик команды /timezone
@router.message(Command("timezone"), StateFilter(None)) # Запускаем только если не в другом состоянии
async def handle_timezone_command(message: Message, state: FSMContext):
    """Начинает процесс установки часового пояса."""
    user_id = message.from_user.id
    logger.info(f"Пользователь {user_id} вызвал команду /timezone.")

    if not db.db_pool:
        await message.answer("Проблема с подключением к базе данных.", reply_markup=main_action_keyboard())
        return

    # Получаем текущий часовой пояс пользователя
    current_tz = await db.get_user_timezone(db.db_pool, user_id)

    await message.answer(
        f"Ваш текущий часовой пояс: <b>{current_tz}</b>\n\n"
        f"Пожалуйста, введите ваш часовой пояс в формате базы данных TZ "
        f"(например, <code>Europe/Moscow</code>, <code>America/New_York</code>, <code>Asia/Yekaterinburg</code>).\n\n"
        f"Полный список можно найти здесь: <a href='{TIMEZONE_LIST_URL}'>Список часовых поясов</a>\n\n"
        f"Или нажмите /cancel для отмены.",
        reply_markup=cancel_keyboard(),
        disable_web_page_preview=True # Отключаем превью ссылки
    )
    # Устанавливаем состояние ожидания ввода таймзоны
    await state.set_state(Settings.waiting_for_timezone)

# Обработчик отмены для состояния настроек
@router.message(Command("cancel"), StateFilter(Settings))
@router.message(F.text == CANCEL_TEXT, StateFilter(Settings))
async def cancel_settings_handler(message: Message, state: FSMContext):
    """Отменяет процесс настройки."""
    current_state = await state.get_state()
    logger.info(f"Пользователь {message.from_user.id} отменил настройку из состояния {current_state}.")
    await state.clear()
    await message.answer("Настройка отменена.", reply_markup=main_action_keyboard())
    await handle_today(message) # Показываем сводку

# Обработчик ввода часового пояса
@router.message(StateFilter(Settings.waiting_for_timezone), F.text)
async def process_timezone_input(message: Message, state: FSMContext):
    """Обрабатывает введенный часовой пояс."""
    user_id = message.from_user.id
    timezone_input = message.text.strip()

    # Проверяем валидность введенного часового пояса
    try:
        # pytz.timezone выбросит исключение, если пояс невалидный
        pytz.timezone(timezone_input)
        is_valid = True
    except pytz.UnknownTimeZoneError:
        is_valid = False
    except Exception as e: # Ловим другие возможные ошибки pytz
        logger.error(f"Ошибка проверки таймзоны '{timezone_input}': {e}")
        is_valid = False


    if is_valid:
        # Часовой пояс валидный, обновляем в базе
        logger.info(f"Пользователь {user_id} ввел валидный часовой пояс: {timezone_input}")
        if db.db_pool:
            try:
                await db.update_user_timezone(db.db_pool, user_id, timezone_input)
                await message.answer(
                    f"✅ Часовой пояс успешно установлен на: <b>{timezone_input}</b>",
                    reply_markup=main_action_keyboard()
                )
                await state.clear() # Очищаем состояние
                await handle_today(message) # Показываем сводку с новым поясом
            except Exception as e:
                logger.error(f"Ошибка обновления часового пояса в БД для {user_id}: {e}", exc_info=True)
                await message.answer(
                    "Произошла ошибка при сохранении часового пояса. Попробуйте еще раз.",
                    reply_markup=cancel_keyboard() # Оставляем возможность отмены
                )
                # Остаемся в том же состоянии
        else:
            logger.error("Пул БД не инициализирован при обновлении таймзоны.")
            await message.answer("Проблема с подключением к базе данных.", reply_markup=main_action_keyboard())
            await state.clear()
    else:
        # Часовой пояс невалидный
        logger.warning(f"Пользователь {user_id} ввел невалидный часовой пояс: {timezone_input}")
        await message.reply(
             f"Извините, <b>{escape(timezone_input)}</b> не является корректным часовым поясом.\n"
             f"Пожалуйста, используйте формат из <a href='{TIMEZONE_LIST_URL}'>этого списка</a> "
             f"(например, <code>Europe/Paris</code>) или нажмите /cancel.",
             disable_web_page_preview=True,
             reply_markup=cancel_keyboard()
        )
        # Остаемся в том же состоянии, чтобы пользователь мог попробовать снова

