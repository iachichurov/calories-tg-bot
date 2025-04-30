import logging
from datetime import datetime, time, date, timedelta, UTC
import asyncpg
import pytz
from typing import Optional, List, Dict, Any

from config import DATABASE_URL, DATABASE_URL_LOG

logger = logging.getLogger(__name__)

db_pool: asyncpg.Pool | None = None

async def create_db_pool():
    """Создает пул соединений с базой данных."""
    global db_pool
    if db_pool: return db_pool
    logger.info("Создание пула соединений с PostgreSQL...")
    logger.info(f"Используется строка подключения: {DATABASE_URL_LOG}")
    try:
        db_pool = await asyncpg.create_pool(DATABASE_URL, max_size=10)
        logger.info("Пул соединений успешно создан.")
        await create_tables_if_not_exist(db_pool)
    except Exception as e:
        logger.critical(f"Не удалось подключиться к базе данных: {e}", exc_info=True)
        exit("Ошибка подключения к БД")
    return db_pool

async def close_db_pool():
    """Закрывает пул соединений с базой данных."""
    global db_pool
    if db_pool:
        logger.info("Закрытие пула соединений...")
        await db_pool.close()
        db_pool = None
        logger.info("Пул соединений закрыт.")

async def create_tables_if_not_exist(pool: asyncpg.Pool):
    """Создает таблицы users, user_products, food_entries, если они еще не существуют."""
    async with pool.acquire() as connection:
        async with connection.transaction():
            # Таблица users
            await connection.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT PRIMARY KEY, first_name VARCHAR(255), last_name VARCHAR(255),
                    username VARCHAR(255), created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), timezone VARCHAR(64) DEFAULT 'UTC',
                    daily_calorie_goal INTEGER
                );
            """)
            # Таблица user_products
            await connection.execute("""
                CREATE TABLE IF NOT EXISTS user_products (
                    product_id SERIAL PRIMARY KEY, user_id BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                    product_name VARCHAR(255) NOT NULL, calories_per_100g INTEGER NOT NULL CHECK (calories_per_100g >= 0),
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), last_used_at TIMESTAMPTZ,
                    CONSTRAINT user_products_user_id_product_name_key UNIQUE (user_id, product_name)
                );
            """)
            # Индекс для user_products
            await connection.execute("""
                CREATE INDEX IF NOT EXISTS idx_user_products_user_id_name ON user_products (user_id, product_name);
            """)
            # Индекс GIN для LIKE
            await connection.execute("""
                CREATE INDEX IF NOT EXISTS idx_user_products_name_gin ON user_products USING gin (product_name gin_trgm_ops);
            """)
            # Таблица food_entries
            await connection.execute("""
                CREATE TABLE IF NOT EXISTS food_entries (
                    entry_id SERIAL PRIMARY KEY, user_id BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                    product_name VARCHAR(255) NOT NULL, weight_grams INTEGER NOT NULL CHECK (weight_grams > 0),
                    calories_consumed INTEGER NOT NULL CHECK (calories_consumed >= 0),
                    entry_timestamp TIMESTAMPTZ NOT NULL -- Время в UTC
                );
            """)
            # Индекс для food_entries
            await connection.execute("""
                CREATE INDEX IF NOT EXISTS idx_food_entries_user_id_timestamp ON food_entries (user_id, entry_timestamp);
            """)
            # Функция и триггер для updated_at
            await connection.execute("""
                CREATE OR REPLACE FUNCTION update_updated_at_column() RETURNS TRIGGER AS $$
                BEGIN NEW.updated_at = NOW(); RETURN NEW; END;
                $$ language 'plpgsql';
            """)
            await connection.execute("""
                DROP TRIGGER IF EXISTS update_users_updated_at ON users;
                CREATE TRIGGER update_users_updated_at BEFORE UPDATE ON users FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
            """)
            logger.info("Проверка и создание таблиц завершены.")


async def add_or_update_user(pool: asyncpg.Pool, user_id: int, first_name: str | None, last_name: str | None, username: str | None):
    """Добавляет нового пользователя или обновляет данные существующего."""
    sql = """
        INSERT INTO users (user_id, first_name, last_name, username) VALUES ($1, $2, $3, $4)
        ON CONFLICT (user_id) DO UPDATE SET
            first_name = EXCLUDED.first_name, last_name = EXCLUDED.last_name,
            username = EXCLUDED.username, updated_at = NOW()
        RETURNING created_at = updated_at;
    """
    async with pool.acquire() as connection:
        try:
            is_new_user = await connection.fetchval(sql, user_id, first_name, last_name, username)
            logger.info(f"Пользователь {user_id} {'зарегистрирован' if is_new_user else 'обновлен'}.")
        except Exception as e:
            logger.error(f"Ошибка при добавлении/обновлении пользователя {user_id}: {e}", exc_info=True)

async def get_user_timezone(pool: asyncpg.Pool, user_id: int) -> str:
    """Получает часовой пояс пользователя из базы данных."""
    sql = "SELECT timezone FROM users WHERE user_id = $1;"
    async with pool.acquire() as connection:
        try:
            tz_name = await connection.fetchval(sql, user_id)
            # --- ОТЛАДОЧНЫЙ ЛОГ ---
            logger.debug(f"Получен часовой пояс для {user_id}: '{tz_name}' (возвращаем '{tz_name if tz_name else 'UTC'}')")
            # --- КОНЕЦ ЛОГА ---
            return tz_name if tz_name else 'UTC'
        except Exception as e:
            logger.error(f"Ошибка при получении часового пояса для {user_id}: {e}", exc_info=True)
            return 'UTC'

async def update_user_timezone(pool: asyncpg.Pool, user_id: int, timezone: str):
    """Обновляет часовой пояс пользователя в базе данных."""
    try:
        pytz.timezone(timezone)
    except pytz.UnknownTimeZoneError:
        logger.error(f"Попытка записать невалидный часовой пояс '{timezone}' для {user_id}")
        raise ValueError(f"Некорректный часовой пояс: {timezone}")

    sql = "UPDATE users SET timezone = $1 WHERE user_id = $2;"
    async with pool.acquire() as connection:
        try:
            result = await connection.execute(sql, timezone, user_id)
            if result == 'UPDATE 1': logger.info(f"Часовой пояс для пользователя {user_id} обновлен на '{timezone}'.")
            else: logger.warning(f"Не удалось обновить часовой пояс для {user_id} (пользователь не найден?).")
        except Exception as e: logger.error(f"Ошибка при обновлении часового пояса для {user_id}: {e}", exc_info=True); raise

async def get_food_entries_for_period(pool: asyncpg.Pool, user_id: int, start_dt_local: datetime, end_dt_exclusive_local: datetime) -> List[asyncpg.Record]:
    """
    Получает список записей о еде пользователя за указанный период [start, end).
    Принимает aware datetime объекты в ЛОКАЛЬНОМ часовом поясе пользователя.
    Конвертирует их в UTC для запроса к базе данных.
    """
    # Конвертируем локальные границы в UTC
    start_dt_utc = start_dt_local.astimezone(pytz.utc)
    end_dt_exclusive_utc = end_dt_exclusive_local.astimezone(pytz.utc)

    # --- ОТЛАДОЧНЫЙ ЛОГ ---
    logger.debug(f"Запрос записей для {user_id}. Локальные границы: [{start_dt_local}, {end_dt_exclusive_local}). UTC границы: [{start_dt_utc}, {end_dt_exclusive_utc})")
    # --- КОНЕЦ ЛОГА ---

    # SQL-запрос для выборки записей в заданном UTC диапазоне [start, end)
    sql = """
        SELECT product_name, weight_grams, calories_consumed, entry_timestamp
        FROM food_entries
        WHERE user_id = $1 AND entry_timestamp >= $2 AND entry_timestamp < $3 -- Используем < для верхней границы
        ORDER BY entry_timestamp ASC;
    """
    async with pool.acquire() as connection:
        try:
            rows = await connection.fetch(sql, user_id, start_dt_utc, end_dt_exclusive_utc)
            logger.debug(f"Получено {len(rows)} записей для {user_id} за период.")
            # --- ОТЛАДОЧНЫЙ ЛОГ (если нужно посмотреть сами записи) ---
            # for i, row in enumerate(rows):
            #     logger.debug(f"  Запись {i+1}: {row['product_name']}, UTC={row['entry_timestamp']}")
            # --- КОНЕЦ ЛОГА ---
            return rows
        except Exception as e:
            logger.error(f"Ошибка при получении записей за период (UTC {start_dt_utc} - {end_dt_exclusive_utc}) для {user_id}: {e}", exc_info=True); return []

async def get_todays_food_entries(pool: asyncpg.Pool, user_id: int, tz_name: str) -> List[asyncpg.Record]:
    """Получает список записей о еде пользователя за сегодня (в его часовом поясе)."""
    try: user_tz = pytz.timezone(tz_name)
    except pytz.UnknownTimeZoneError: logger.warning(f"Некорректный TZ '{tz_name}' для {user_id}. Используется UTC."); user_tz = pytz.utc

    # Определяем начало сегодняшнего дня и начало следующего дня в локальном времени
    now_local = datetime.now(user_tz)
    today_start_local = datetime.combine(now_local.date(), time.min, tzinfo=user_tz)
    next_day_start_local = today_start_local + timedelta(days=1)

    # --- ОТЛАДОЧНЫЙ ЛОГ ---
    logger.debug(f"get_todays_food_entries для {user_id} (TZ: {tz_name}). Локальные границы: [{today_start_local}, {next_day_start_local})")
    # --- КОНЕЦ ЛОГА ---

    # Вызываем общую функцию с интервалом [today_start, next_day_start)
    return await get_food_entries_for_period(pool, user_id, today_start_local, next_day_start_local)

async def get_last_n_days_entries(pool: asyncpg.Pool, user_id: int, tz_name: str, days: int = 7) -> List[asyncpg.Record]:
    """Получает список записей о еде пользователя за последние N дней (в его часовом поясе)."""
    try: user_tz = pytz.timezone(tz_name)
    except pytz.UnknownTimeZoneError: logger.warning(f"Некорректный TZ '{tz_name}' для {user_id}. Используется UTC."); user_tz = pytz.utc

    # Определяем начало первого дня периода и начало дня ПОСЛЕ последнего дня периода
    now_local = datetime.now(user_tz)
    today_start_local = datetime.combine(now_local.date(), time.min, tzinfo=user_tz)
    start_date_local = today_start_local - timedelta(days=days-1) # Начало первого дня (включительно)
    end_date_exclusive_local = today_start_local + timedelta(days=1) # Начало дня ПОСЛЕ сегодняшнего (не включительно)

    logger.info(f"Запрос записей для {user_id} с {start_date_local} по <{end_date_exclusive_local} ({days} дней, TZ: {tz_name})")
    # Вызываем общую функцию
    return await get_food_entries_for_period(pool, user_id, start_date_local, end_date_exclusive_local)

async def get_current_month_entries(pool: asyncpg.Pool, user_id: int, tz_name: str) -> List[asyncpg.Record]:
    """Получает список записей о еде пользователя за текущий календарный месяц (в его часовом поясе)."""
    try: user_tz = pytz.timezone(tz_name)
    except pytz.UnknownTimeZoneError: logger.warning(f"Некорректный TZ '{tz_name}' для {user_id}. Используется UTC."); user_tz = pytz.utc

    # Определяем начало текущего месяца и начало следующего месяца в локальном времени
    now_local = datetime.now(user_tz)
    current_date_local = now_local.date()
    start_date_local = datetime(current_date_local.year, current_date_local.month, 1, tzinfo=user_tz) # Первое число месяца

    # Вычисляем начало следующего месяца
    if current_date_local.month == 12:
        next_month_start_local = datetime(current_date_local.year + 1, 1, 1, tzinfo=user_tz)
    else:
        next_month_start_local = datetime(current_date_local.year, current_date_local.month + 1, 1, tzinfo=user_tz)

    # Используем интервал [start_of_month, start_of_next_month)
    end_date_exclusive_local = next_month_start_local

    logger.info(f"Запрос записей для {user_id} с {start_date_local} по <{end_date_exclusive_local} (текущий месяц, TZ: {tz_name})")
    # Вызываем общую функцию
    return await get_food_entries_for_period(pool, user_id, start_date_local, end_date_exclusive_local)


async def add_user_product(pool: asyncpg.Pool, user_id: int, product_name: str, calories_100g: int) -> str:
    """Добавляет/обновляет продукт в личном списке пользователя."""
    normalized_product_name = ' '.join(product_name.strip().split()).lower()
    sql = """
        INSERT INTO user_products (user_id, product_name, calories_per_100g, last_used_at) VALUES ($1, $2, $3, NOW())
        ON CONFLICT ON CONSTRAINT user_products_user_id_product_name_key DO UPDATE SET calories_per_100g = EXCLUDED.calories_per_100g, last_used_at = NOW();
    """
    async with pool.acquire() as connection:
        try: await connection.execute(sql, user_id, normalized_product_name, calories_100g); logger.info(f"Продукт '{normalized_product_name}' добавлен/обновлен для {user_id}.")
        except Exception as e: logger.error(f"Ошибка при добавлении/обновлении продукта '{normalized_product_name}' для {user_id}: {e}", exc_info=True); raise
    return normalized_product_name

async def add_food_entry(pool: asyncpg.Pool, user_id: int, product_name: str, weight_grams: int, calories_consumed: int):
    """Добавляет запись о приеме пищи с текущим временем UTC."""
    current_utc_time = datetime.now(UTC) # Получаем текущее время UTC
    # --- ОТЛАДОЧНЫЙ ЛОГ ---
    logger.debug(f"Добавление записи для {user_id}: Продукт='{product_name}', Вес={weight_grams}, Ккал={calories_consumed}, Время UTC={current_utc_time}")
    # --- КОНЕЦ ЛОГА ---
    sql = "INSERT INTO food_entries (user_id, product_name, weight_grams, calories_consumed, entry_timestamp) VALUES ($1, $2, $3, $4, $5);"
    async with pool.acquire() as connection:
        try: await connection.execute(sql, user_id, product_name, weight_grams, calories_consumed, current_utc_time); logger.info(f"Запись о еде добавлена для {user_id}.")
        except Exception as e: logger.error(f"Ошибка при добавлении записи о еде для {user_id}: {e}", exc_info=True); raise

async def get_user_product(pool: asyncpg.Pool, user_id: int, product_name: str) -> Optional[asyncpg.Record]:
    """Ищет продукт по точному совпадению нормализованного имени."""
    normalized_product_name = ' '.join(product_name.strip().split()).lower()
    sql = "SELECT product_id, product_name, calories_per_100g FROM user_products WHERE user_id = $1 AND product_name = $2;"
    async with pool.acquire() as connection:
        try: row = await connection.fetchrow(sql, user_id, normalized_product_name); logger.info(f"Поиск точного совпадения для '{normalized_product_name}' у {user_id}: {'Найден' if row else 'Не найден'}"); return row
        except Exception as e: logger.error(f"Ошибка при точном поиске продукта '{normalized_product_name}' для {user_id}: {e}", exc_info=True); return None

async def get_user_product_by_id(pool: asyncpg.Pool, user_id: int, product_id: int) -> Optional[asyncpg.Record]:
    """Ищет продукт в личном списке пользователя по его ID."""
    sql = "SELECT product_id, product_name, calories_per_100g FROM user_products WHERE user_id = $1 AND product_id = $2;"
    async with pool.acquire() as connection:
        try:
            row = await connection.fetchrow(sql, user_id, product_id)
            if row: logger.info(f"Поиск по ID={product_id} у {user_id}: Найден '{row['product_name']}'")
            else: logger.warning(f"Поиск по ID={product_id} у {user_id}: Не найден!")
            return row
        except Exception as e: logger.error(f"Ошибка при поиске продукта по ID={product_id} для {user_id}: {e}", exc_info=True); return None

async def search_user_products(pool: asyncpg.Pool, user_id: int, search_query: str, limit: int = 5) -> List[asyncpg.Record]:
    """Ищет продукты в личном списке пользователя по началу строки (LIKE 'query%')."""
    normalized_query = ' '.join(search_query.strip().split()).lower(); pattern = normalized_query + '%'
    sql = """
        SELECT product_id, product_name, calories_per_100g FROM user_products
        WHERE user_id = $1 AND product_name LIKE $2 ORDER BY last_used_at DESC NULLS LAST LIMIT $3;
    """
    async with pool.acquire() as connection:
        try: rows = await connection.fetch(sql, user_id, pattern, limit); logger.info(f"Контекстный поиск для '{normalized_query}%' у {user_id}: Найдено {len(rows)} записей."); return rows
        except Exception as e:
            if isinstance(e, asyncpg.UndefinedFunctionError) and 'gin_trgm_ops' in str(e): logger.error(f"Ошибка контекстного поиска: Расширение 'pg_trgm' не установлено? Выполните 'CREATE EXTENSION IF NOT EXISTS pg_trgm;' в БД.")
            logger.error(f"Ошибка при контекстном поиске '{pattern}' для {user_id}: {e}", exc_info=True); return []
