from aiogram.fsm.state import State, StatesGroup

class AddFood(StatesGroup):
    """Состояния для процесса добавления продукта."""
    waiting_for_product_name = State()
    waiting_for_weight = State()
    waiting_for_calories = State()
    waiting_for_api_confirmation = State()
    waiting_for_api_choice = State()

# --- Обновляем состояния для настроек ---
class Settings(StatesGroup):
    """Состояния для настройки профиля пользователя."""
    waiting_for_action = State() # Ожидание выбора параметра для изменения
    waiting_for_height = State() # Ожидание ввода роста
    waiting_for_weight = State() # Ожидание ввода веса
    # Для пола и цели будем использовать CallbackQuery, отдельное состояние не нужно
    waiting_for_timezone = State() # <-- ВОССТАНОВЛЕНО: Ожидание ввода часового пояса

