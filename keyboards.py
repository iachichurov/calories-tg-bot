import logging
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton
)
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder
from typing import List, Dict, Any

# --- Callback Data Префиксы ---
PRODUCT_SELECT_CALLBACK_PREFIX = "prod_select:"
SETTINGS_ACTION_CALLBACK_PREFIX = "set_action:"
GENDER_SELECT_CALLBACK_PREFIX = "set_gender:"
GOAL_SELECT_CALLBACK_PREFIX = "set_goal:"
# --- НОВЫЙ ПРЕФИКС/ДЕЙСТВИЕ для возврата в меню настроек ---
SETTINGS_SHOW_MENU_ACTION = "show_menu"

# --- Тексты для Reply кнопок ---
CANCEL_TEXT = "/cancel"
FIND_CALORIES_TEXT = "🔍 Найти калорийность"
ADD_PRODUCT_TEXT = "➕ Добавить продукт"
CONFIRM_API_TEXT = "✅ Да, верно"
EDIT_API_TEXT = "✏️ Изменить калории"
MANUAL_INPUT_TEXT = "⌨️ Ввести вручную"

# --- Reply клавиатуры ---
# (Функции cancel_keyboard, request_calories_keyboard, main_action_keyboard,
# confirm_edit_keyboard, select_api_product_keyboard остаются без изменений)
def cancel_keyboard() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder(); builder.add(KeyboardButton(text=CANCEL_TEXT))
    return builder.as_markup(resize_keyboard=True, one_time_keyboard=False)
def request_calories_keyboard() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder(); builder.row(KeyboardButton(text=FIND_CALORIES_TEXT), KeyboardButton(text=CANCEL_TEXT))
    return builder.as_markup(resize_keyboard=True, one_time_keyboard=False)
def main_action_keyboard() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder(); builder.add(KeyboardButton(text=ADD_PRODUCT_TEXT))
    return builder.as_markup(resize_keyboard=True, one_time_keyboard=False)
def confirm_edit_keyboard() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder(); builder.row(KeyboardButton(text=CONFIRM_API_TEXT), KeyboardButton(text=EDIT_API_TEXT)); builder.row(KeyboardButton(text=CANCEL_TEXT))
    return builder.as_markup(resize_keyboard=True, one_time_keyboard=False)
def select_api_product_keyboard(options: List[Dict[str, Any]]) -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    for option in options: name = option['name']; calories = option['calories']; button_text = f"{name[:30]}... ({calories} ккал)" if len(name) > 30 else f"{name} ({calories} ккал)"; builder.add(KeyboardButton(text=button_text))
    builder.add(KeyboardButton(text=MANUAL_INPUT_TEXT)); builder.add(KeyboardButton(text=CANCEL_TEXT)); builder.adjust(2)
    return builder.as_markup(resize_keyboard=True)

# --- Inline клавиатуры ---
def product_suggestions_keyboard(suggestions: List[Dict[str, Any]]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for item in suggestions:
        product_id = item['product_id']; name = item['product_name']; calories = item['calories_per_100g']
        button_text = f"{name[:30]}.. ({calories})" if len(name) > 30 else f"{name} ({calories})"
        callback_data = f"{PRODUCT_SELECT_CALLBACK_PREFIX}{product_id}"
        if len(callback_data.encode('utf-8')) <= 64: builder.add(InlineKeyboardButton(text=button_text, callback_data=callback_data))
        else: logging.warning(f"Callback data for product_id {product_id} is too long: {callback_data}")
    builder.adjust(1); return builder.as_markup()

def settings_main_keyboard() -> InlineKeyboardMarkup:
    """Главное меню настроек профиля."""
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🎯 Изменить Цель", callback_data=f"{SETTINGS_ACTION_CALLBACK_PREFIX}change_goal"), InlineKeyboardButton(text="🧍 Изменить Пол", callback_data=f"{SETTINGS_ACTION_CALLBACK_PREFIX}change_gender"))
    builder.row(InlineKeyboardButton(text="📏 Изменить Рост", callback_data=f"{SETTINGS_ACTION_CALLBACK_PREFIX}change_height"), InlineKeyboardButton(text="⚖️ Изменить Вес", callback_data=f"{SETTINGS_ACTION_CALLBACK_PREFIX}change_weight"))
    # Кнопка "Назад" из главного меню - закрывает настройки
    builder.row(InlineKeyboardButton(text="🔙 Закрыть настройки", callback_data=f"{SETTINGS_ACTION_CALLBACK_PREFIX}back")) # Можно изменить текст для ясности
    return builder.as_markup()

def select_goal_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура для выбора цели."""
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="📉 Дефицит", callback_data=f"{GOAL_SELECT_CALLBACK_PREFIX}deficit"))
    builder.row(InlineKeyboardButton(text="維持 Поддержание", callback_data=f"{GOAL_SELECT_CALLBACK_PREFIX}maintenance"))
    builder.row(InlineKeyboardButton(text="📈 Профицит", callback_data=f"{GOAL_SELECT_CALLBACK_PREFIX}surplus"))
    builder.row(InlineKeyboardButton(text="🚫 Не устанавливать", callback_data=f"{GOAL_SELECT_CALLBACK_PREFIX}none"))
    # --- ИЗМЕНЕНО: Используем новый callback_data для возврата в меню ---
    builder.row(InlineKeyboardButton(text="🔙 Назад в настройки", callback_data=f"{SETTINGS_ACTION_CALLBACK_PREFIX}{SETTINGS_SHOW_MENU_ACTION}"))
    return builder.as_markup()

def select_gender_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура для выбора пола."""
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="👨 Мужской", callback_data=f"{GENDER_SELECT_CALLBACK_PREFIX}male"), InlineKeyboardButton(text="👩 Женский", callback_data=f"{GENDER_SELECT_CALLBACK_PREFIX}female"))
    # --- ИЗМЕНЕНО: Используем новый callback_data для возврата в меню ---
    builder.row(InlineKeyboardButton(text="🔙 Назад в настройки", callback_data=f"{SETTINGS_ACTION_CALLBACK_PREFIX}{SETTINGS_SHOW_MENU_ACTION}"))
    return builder.as_markup()

