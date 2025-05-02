import logging
from aiogram import Router, Bot, F # Добавили F для фильтра по тексту
from aiogram.filters import CommandStart, Command, StateFilter # Добавили StateFilter
from aiogram.types import Message, ReplyKeyboardRemove, BotCommand, BotCommandScopeDefault
from aiogram.fsm.context import FSMContext

# Импортируем функции БД и пул соединений
import database as db
# Импортируем обработчик отчетов, чтобы показать сводку после /start
from .reports import handle_today
# Импортируем основную клавиатуру
from keyboards import main_action_keyboard

# Настраиваем логирование
logger = logging.getLogger(__name__)

# Создаем роутер для общих команд
router = Router()

async def set_main_menu(bot: Bot):
    """Функция для настройки кнопки Menu в Telegram."""
    # Список команд для главного меню
    main_menu_commands = [
        BotCommand(command="/start", description="🚀 Запуск / Перезапуск"),
        BotCommand(command="/add", description="➕ Добавить продукт"),
        BotCommand(command="/today", description="📊 Сводка за сегодня"),
        BotCommand(command="/week", description="📅 Отчет за неделю"),
        BotCommand(command="/month", description="🗓️ Отчет за месяц"),
        BotCommand(command="/settings", description="⚙️ Настройки профиля"),
        BotCommand(command="/setweight", description="⚖️ Указать вес"),
        BotCommand(command="/timezone", description="🕒 Часовой пояс"),
        BotCommand(command="/cancel", description="❌ Отменить действие"),
        BotCommand(command="/help", description="❓ Помощь")
    ]
    # Устанавливаем команды для области по умолчанию
    await bot.set_my_commands(main_menu_commands, BotCommandScopeDefault())
    logger.info("Команды в меню установлены.")


@router.message(CommandStart())
async def handle_start_command(message: Message, state: FSMContext):
    """Обработчик команды /start."""
    # Сбрасываем состояние FSM, если пользователь был в каком-то процессе
    current_state = await state.get_state()
    if current_state is not None:
        logger.info(
            f"Сброс состояния {current_state} для пользователя {message.from_user.id}"
        )
        await state.clear()

    user = message.from_user
    logger.info(f"Пользователь {user.id} ({user.full_name}) запустил бота.")

    is_new_user = False
    # Добавляем или обновляем пользователя в БД
    if db.db_pool:
        is_new_user = await db.add_or_update_user(
            pool=db.db_pool,
            user_id=user.id,
            first_name=user.first_name,
            last_name=user.last_name,
            username=user.username
        )
    else:
        # Если нет подключения к БД
        logger.warning("Пул соединений с БД не инициализирован при обработке /start.")
        await message.answer(
            "Возникла проблема с подключением к базе данных. Попробуйте позже.",
            reply_markup=ReplyKeyboardRemove()
        )
        return

    # Формируем приветственное сообщение
    greeting_text = (
        f"Привет, {user.first_name or 'Пользователь'}! 👋\n"
        f"Я бот для учета калорий."
    )
    # Предлагаем настроить профиль новым пользователям
    if is_new_user:
        greeting_text += (
            "\n\nЧтобы я мог рассчитать вашу норму калорий, "
            "пожалуйста, укажите данные вашего профиля в /settings."
        )

    await message.answer(greeting_text)
    # Показываем сводку за сегодня (она покажет основную клавиатуру)
    await handle_today(message)


@router.message(Command("help"))
async def handle_help_command(message: Message):
    """Обработчик команды /help."""
    user_id = message.from_user.id
    logger.info(f"Пользователь {user_id} запросил помощь.")
    # Формируем текст справки
    help_text = (
        "❓ **Помощь:**\n\n"
        "Я бот для учета калорий.\n"
        "Нажми кнопку '➕ Добавить продукт' ниже или используй команду /add.\n"
        "/today - посмотреть, что съедено сегодня и вашу норму калорий.\n"
        "/week - отчет по калориям за последние 7 дней.\n"
        "/month - отчет по калориям за текущий месяц.\n"
        "/settings - настроить ваш профиль (рост, вес, пол, цель) для расчета нормы.\n"
        "/setweight - быстро обновить ваш текущий вес.\n"
        "/timezone - установить ваш часовой пояс.\n"
        "/cancel - отменить текущее действие.\n\n"
        "Просто следуйте инструкциям после ввода команд."
    )
    # Отправляем справку и основную клавиатуру
    await message.answer(help_text, reply_markup=main_action_keyboard())

# Обработчик /cancel вне состояний FSM
@router.message(Command("cancel"), StateFilter(None))
async def handle_cancel_outside_state(message: Message, state: FSMContext):
    """Обрабатывает /cancel, если пользователь не находится в каком-либо состоянии FSM."""
    # Этот обработчик нужен, если пользователь случайно нажмет /cancel,
    # не находясь ни в одном процессе (добавления еды, настроек и т.д.)
    logger.info(f"Пользователь {message.from_user.id} ввел /cancel вне состояния.")
    await message.answer(
        "Нет активного действия для отмены.",
        reply_markup=main_action_keyboard() # Показываем основную клавиатуру
    )

# --- НОВЫЙ ОБРАБОТЧИК: Ловит любой текст вне состояний FSM ---
@router.message(F.text, StateFilter(None))
async def handle_unknown_text(message: Message):
    """Обрабатывает текстовые сообщения, для которых нет других обработчиков."""
    logger.warning(
        f"Получено неизвестное текстовое сообщение от {message.from_user.id} "
        f"вне состояния: '{message.text}'"
    )
    await message.reply(
        "Извините, я не понимаю это сообщение. "
        "Используйте кнопки или команды из меню /.",
        reply_markup=main_action_keyboard() # Переотправляем основную клавиатуру
    )

