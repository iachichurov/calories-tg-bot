from aiogram.fsm.state import State, StatesGroup

class AddFood(StatesGroup):
    """Состояния для процесса добавления продукта."""
    waiting_for_product_name = State()
    waiting_for_weight = State()
    waiting_for_calories = State()
    waiting_for_api_confirmation = State()
    waiting_for_api_choice = State()

# --- НОВЫЙ КЛАСС СОСТОЯНИЙ ---
class Settings(StatesGroup):
    """Состояния для настроек пользователя."""
    waiting_for_timezone = State()
    # Здесь могут быть другие настройки в будущем

