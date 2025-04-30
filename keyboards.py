import logging # Added logging for warnings
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton # <-- Added Inline types
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder # <-- Added Inline builder
from typing import List, Dict, Any # For type hints

# --- Callback Data Prefix ---
# Used to identify callbacks specifically for product selection
PRODUCT_SELECT_CALLBACK_PREFIX = "prod_select:"

# --- Reply Keyboard Button Texts ---
CANCEL_TEXT = "/cancel"
FIND_CALORIES_TEXT = "🔍 Найти калорийность"
ADD_PRODUCT_TEXT = "➕ Добавить продукт"
CONFIRM_API_TEXT = "✅ Да, верно"
EDIT_API_TEXT = "✏️ Изменить калории"
MANUAL_INPUT_TEXT = "⌨️ Ввести вручную"

# --- Reply Keyboards ---

def cancel_keyboard() -> ReplyKeyboardMarkup:
    """Creates a reply keyboard with just a /cancel button."""
    builder = ReplyKeyboardBuilder()
    builder.add(KeyboardButton(text=CANCEL_TEXT))
    # resize_keyboard=True makes the keyboard smaller
    # one_time_keyboard=False makes it persistent until another keyboard is sent
    return builder.as_markup(resize_keyboard=True, one_time_keyboard=False)

def request_calories_keyboard() -> ReplyKeyboardMarkup:
    """Keyboard shown when asking for calories or API search."""
    builder = ReplyKeyboardBuilder()
    # Buttons arranged in a row
    builder.row(KeyboardButton(text=FIND_CALORIES_TEXT), KeyboardButton(text=CANCEL_TEXT))
    return builder.as_markup(resize_keyboard=True, one_time_keyboard=False)

def main_action_keyboard() -> ReplyKeyboardMarkup:
    """The main keyboard shown in the chat with the primary action."""
    builder = ReplyKeyboardBuilder()
    builder.add(KeyboardButton(text=ADD_PRODUCT_TEXT))
    # Can add other main actions here later, e.g., "View Today's Summary"
    return builder.as_markup(resize_keyboard=True, one_time_keyboard=False)

def confirm_edit_keyboard() -> ReplyKeyboardMarkup:
    """Keyboard for confirming or editing API-found calorie value."""
    builder = ReplyKeyboardBuilder()
    # Confirmation and Edit buttons in the first row
    builder.row(KeyboardButton(text=CONFIRM_API_TEXT), KeyboardButton(text=EDIT_API_TEXT))
    # Cancel button in the second row
    builder.row(KeyboardButton(text=CANCEL_TEXT))
    return builder.as_markup(resize_keyboard=True, one_time_keyboard=False)

def select_api_product_keyboard(options: List[Dict[str, Any]]) -> ReplyKeyboardMarkup:
    """Reply keyboard to select one of the options found via API."""
    builder = ReplyKeyboardBuilder()
    for option in options:
        name = option['name']
        calories = option['calories']
        # Truncate long names for button text
        button_text = f"{name[:30]}... ({calories} ккал)" if len(name) > 30 else f"{name} ({calories} ккал)"
        builder.add(KeyboardButton(text=button_text))
    # Add options for manual input or cancellation
    builder.add(KeyboardButton(text=MANUAL_INPUT_TEXT))
    builder.add(KeyboardButton(text=CANCEL_TEXT))
    # Adjust layout, e.g., 2 buttons per row
    builder.adjust(2)
    return builder.as_markup(resize_keyboard=True)

# --- Inline Keyboard ---
def product_suggestions_keyboard(suggestions: List[Dict[str, Any]]) -> InlineKeyboardMarkup:
    """
    Creates an inline keyboard with product suggestions from the user's database.
    suggestions: list of dicts [{'product_id': int, 'product_name': str, 'calories_per_100g': int}]
    """
    builder = InlineKeyboardBuilder()
    for item in suggestions:
        product_id = item['product_id'] # <-- Get the ID
        name = item['product_name']
        calories = item['calories_per_100g']
        # Format button text, truncating long names
        button_text = f"{name[:30]}.. ({calories})" if len(name) > 30 else f"{name} ({calories})"
        # --- CHANGED: Use product_id in callback_data ---
        # Construct callback data using the prefix and product ID
        callback_data = f"{PRODUCT_SELECT_CALLBACK_PREFIX}{product_id}"
        # Basic check for callback data length (Telegram limit is 1-64 bytes)
        if len(callback_data.encode('utf-8')) <= 64:
            builder.add(InlineKeyboardButton(text=button_text, callback_data=callback_data))
        else:
            # Log a warning if callback data is too long (shouldn't happen with IDs)
            logging.warning(f"Callback data for product_id {product_id} is too long: {callback_data}")

    # Adjust layout to have 1 button per row for better readability
    builder.adjust(1)
    return builder.as_markup()
