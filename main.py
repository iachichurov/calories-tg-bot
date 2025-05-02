import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage

# Импортируем конфигурацию
import config
# Импортируем функции для работы с БД
import database as db
# Импортируем главный роутер из пакета handlers
from handlers import all_routers
# Импортируем функцию установки меню
from handlers.common import set_main_menu

# --- Настройка логирования ---
# Устанавливаем базовую конфигурацию логирования
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(name)s - %(message)s'
)
# Получаем логгер для этого модуля
logger = logging.getLogger(__name__)

# --- Основная функция запуска ---
async def main():
    """Главная асинхронная функция для запуска бота."""
    logger.info("Запуск бота...")

    # Инициализация хранилища FSM (пока в памяти)
    storage = MemoryStorage()

    # Инициализация бота с настройками по умолчанию (HTML parse_mode)
    defaults = DefaultBotProperties(parse_mode="HTML")
    bot = Bot(token=config.BOT_TOKEN, default=defaults)

    # Инициализация диспетчера
    dp = Dispatcher(storage=storage)

    # Подключаем роутеры из папки handlers
    dp.include_router(all_routers)

    # Регистрируем асинхронные функции на события startup и shutdown
    dp.startup.register(db.create_db_pool)  # Создаем пул соединений при старте
    dp.startup.register(set_main_menu)      # Устанавливаем меню команд
    dp.shutdown.register(db.close_db_pool) # Закрываем пул соединений при остановке

    # Удаляем вебхук перед запуском в режиме polling
    await bot.delete_webhook(drop_pending_updates=True)

    logger.info("Начало опроса Telegram...")
    # Запускаем бота в режиме опроса (polling)
    try:
        await dp.start_polling(bot)
    finally:
        # Корректно закрываем сессию бота при завершении
        await bot.session.close()
        logger.info("Сессия бота закрыта.")


if __name__ == "__main__":
    try:
        # Запускаем асинхронную функцию main
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        # Обрабатываем прерывание с клавиатуры (Ctrl+C)
        logger.info("Бот остановлен вручную.")
    except Exception as e:
        # Логируем критические ошибки при запуске
        logger.critical(f"Критическая ошибка при запуске бота: {e}", exc_info=True)

