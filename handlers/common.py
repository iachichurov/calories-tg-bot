import logging
from aiogram import Router, Bot
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, ReplyKeyboardRemove, BotCommand, BotCommandScopeDefault
from aiogram.fsm.context import FSMContext

# Импортируем функции БД и пул соединений
import database as db
# Импортируем обработчик отчетов, чтобы показать сводку после /start
from .reports import handle_today
# Импортируем основную клавиатуру
from keyboards import main_action_keyboard

logger = logging.getLogger(__name__)

# Создаем роутер для общих команд
router = Router()

async def set_main_menu(bot: Bot):
    """Функция для настройки кнопки Menu в Telegram"""
    main_menu_commands = [
        BotCommand(command="/start", description="🚀 Запуск / Перезапуск"),
        BotCommand(command="/add", description="➕ Добавить продукт"),
        BotCommand(command="/today", description="📊 Сводка за сегодня"),
        BotCommand(command="/week", description="📅 Отчет за неделю"),
        BotCommand(command="/month", description="🗓️ Отчет за месяц"),
        BotCommand(command="/settings", description="⚙️ Настройки профиля"), # <--- Добавили команду
        BotCommand(command="/setweight", description="⚖️ Указать вес"), # <-- Добавили команду для веса
        BotCommand(command="/timezone", description="🕒 Часовой пояс"), # Оставили, если нужна
        BotCommand(command="/cancel", description="❌ Отменить действие"),
        BotCommand(command="/help", description="❓ Помощь")
    ]
    await bot.set_my_commands(main_menu_commands, BotCommandScopeDefault())
    logger.info("Команды в меню установлены.")


@router.message(CommandStart())
async def handle_start_command(message: Message, state: FSMContext):
    """Обработчик команды /start"""
    current_state = await state.get_state()
    if current_state is not None:
        logger.info(f"Сброс состояния {current_state} для пользователя {message.from_user.id}")
        await state.clear()

    user = message.from_user
    logger.info(f"Пользователь {user.id} ({user.full_name}) запустил бота.")

    is_new_user = False
    if db.db_pool:
        # --- ИЗМЕНЕНО: Получаем флаг нового пользователя ---
        is_new_user = await db.add_or_update_user(
            pool=db.db_pool, user_id=user.id, first_name=user.first_name,
            last_name=user.last_name, username=user.username
        )
    else:
        logger.warning("Пул соединений с БД не инициализирован при обработке /start.")
        await message.answer("Возникла проблема с подключением к базе данных. Попробуйте позже.", reply_markup=ReplyKeyboardRemove())
        return

    # --- ИЗМЕНЕНО: Приветствие и предложение настроить профиль для новых ---
    greeting_text = f"Привет, {user.first_name or 'Пользователь'}! 👋\nЯ бот для учета калорий."
    if is_new_user:
        greeting_text += "\n\nЧтобы я мог рассчитать вашу норму калорий, пожалуйста, укажите данные вашего профиля в /settings."

    await message.answer(greeting_text)
    # Показываем сводку за сегодня (она покажет основную клавиатуру)
    await handle_today(message)


@router.message(Command("help"))
async def handle_help_command(message: Message):
    """Обработчик команды /help"""
    user_id = message.from_user.id
    logger.info(f"Пользователь {user_id} запросил помощь.")
    await message.answer(
        "❓ **Помощь:**\n\n"
        "Я бот для учета калорий.\n"
        "Нажми кнопку '➕ Добавить продукт' ниже или используй команду /add.\n"
        "/today - посмотреть, что съедено сегодня и вашу норму калорий.\n"
        "/week - отчет по калориям за последние 7 дней.\n"
        "/month - отчет по калориям за текущий месяц.\n"
        "/settings - настроить ваш профиль (рост, вес, пол, цель) для расчета нормы.\n" # <--- Обновили описание
        "/setweight - быстро обновить ваш текущий вес.\n"
        "/timezone - установить ваш часовой пояс.\n"
        "/cancel - отменить текущее действие.\n\n"
        "Просто следуйте инструкциям после ввода команд.",
        reply_markup=main_action_keyboard()
    )

# Обработчик /cancel вне состояний
@router.message(Command("cancel"))
async def handle_cancel_outside_state(message: Message, state: FSMContext):
    """Обрабатывает /cancel, если пользователь не находится в каком-либо состоянии FSM."""
    current_state = await state.get_state()
    if current_state is None:
        await message.answer("Нет активного действия для отмены.", reply_markup=main_action_keyboard())
        return
    logger.warning(f"Пользователь {message.from_user.id} ввел /cancel в неожиданном состоянии {current_state}. Сброс.")
    await state.clear()
    await message.answer("Действие отменено.", reply_markup=main_action_keyboard())
    await handle_today(message)

