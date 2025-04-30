import os
from dotenv import load_dotenv
from urllib.parse import quote_plus
import logging

logger = logging.getLogger(__name__)

# Загружаем переменные из файла .env
load_dotenv()

# --- Токен Telegram-бота ---
BOT_TOKEN = os.getenv("BOT_TOKEN")

# --- Данные для подключения к БД ---
DB_USER = os.getenv("DB_USER")
DB_PASS = os.getenv("DB_PASS")
DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT", 5432)
DB_NAME = os.getenv("DB_NAME")

# Проверка наличия всех необходимых переменных окружения
if not all([BOT_TOKEN, DB_USER, DB_PASS, DB_HOST, DB_NAME]):
    logger.critical("Не хватает переменных окружения для запуска бота и подключения к БД!")
    exit("Ошибка: Необходимые переменные окружения не установлены.")

# URL-кодируем пароль
DB_PASS_ENCODED = quote_plus(DB_PASS)

# Строка подключения к PostgreSQL
DATABASE_URL = f"postgresql://{DB_USER}:{DB_PASS_ENCODED}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

# Строка подключения для логирования (без пароля)
DATABASE_URL_LOG = f"postgresql://{DB_USER}:******@{DB_HOST}:{DB_PORT}/{DB_NAME}"

