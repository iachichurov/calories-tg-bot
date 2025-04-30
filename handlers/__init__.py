from aiogram import Router

# Импортируем роутеры из каждого модуля обработчиков
from .common import router as common_router
from .add_food import router as add_food_router
from .reports import router as reports_router
from .settings import router as settings_router # <--- Добавили импорт

# Создаем главный роутер для всех обработчиков
all_routers = Router()

# Включаем роутеры из модулей в главный роутер
# Порядок важен: FSM-обработчики (add_food, settings) должны идти до общих команд.
all_routers.include_router(settings_router) # <--- Добавили роутер настроек
all_routers.include_router(add_food_router)
all_routers.include_router(reports_router)
all_routers.include_router(common_router) # Общие команды (включая /start, /help) регистрируем последними

