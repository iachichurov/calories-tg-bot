import os
from dotenv import load_dotenv
from urllib.parse import quote_plus
import logging

logger = logging.getLogger(__name__)

# Загружаем переменные из файла .env
load_dotenv()

# --- Токен Telegram-бота ---
# BOT_TOKEN - токен для доступа к API Telegram-бота
BOT_TOKEN = os.getenv("BOT_TOKEN")

# --- Данные для подключения к БД ---
# DB_USER - имя пользователя для подключения к базе данных
# DB_PASS - пароль пользователя для подключения к базе данных
# DB_HOST - хост, на котором запущен сервер базы данных
# DB_PORT - порт, на котором работает сервер базы данных (по умолчанию 5432 для PostgreSQL)
# DB_NAME - имя базы данных, к которой необходимо подключиться
DB_USER = os.getenv("DB_USER")
DB_PASS = os.getenv("DB_PASS")
DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT", 5432)
DB_NAME = os.getenv("DB_NAME")

# --- Настройки FSM хранилища ---
# FSM_STORAGE - тип хранилища FSM: 'memory' или 'redis'
# REDIS_URL - URL подключения к Redis (например redis://redis:6379/0)
FSM_STORAGE = os.getenv("FSM_STORAGE", "redis").strip().lower()
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")

# Проверка наличия всех необходимых переменных окружения
# Если какой-либо из параметров подключения отсутствует, логируем критическую ошибку и выходим из программы
if not all([BOT_TOKEN, DB_USER, DB_PASS, DB_HOST, DB_NAME]):
    logger.critical("Не хватает переменных окружения для запуска бота и подключения к БД!")
    raise RuntimeError("Ошибка: Необходимые переменные окружения не установлены.")

# URL-кодируем пароль
DB_PASS_ENCODED = quote_plus(DB_PASS)

# Строка подключения к PostgreSQL
DATABASE_URL = f"postgresql://{DB_USER}:{DB_PASS_ENCODED}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

# Строка подключения для логирования (без пароля)
DATABASE_URL_LOG = f"postgresql://{DB_USER}:******@{DB_HOST}:{DB_PORT}/{DB_NAME}"
