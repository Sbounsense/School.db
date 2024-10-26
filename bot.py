import sqlite3
import logging
import os
import qrcode
from io import BytesIO
from PIL import Image
from pyzbar.pyzbar import decode
from telegram import (
    Update,
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove,
    InputMediaPhoto,
    Location,
    ParseMode
)
from telegram.ext import (
    Updater,
    CommandHandler,
    MessageHandler,
    Filters,
    CallbackContext,
    ConversationHandler
)
import re
from datetime import datetime

# Включаем логирование
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

# Конфигурация
DATABASE = 'school_bot.db'
TOKEN = '7640183456:AAHoRsfFowq9KTbH-XLi-krhDC42MjlbklM'  # Замените на новый токен вашего бота
BOT_USERNAME = 'School292_bot'  # Замените на юзернейм вашего бота без @

# Первоначальный список администраторов по Telegram ID
INITIAL_ADMIN_IDS = [
    713459791,  # Замените на реальные Telegram ID администраторов
    701246470,
    # Добавьте дополнительные Telegram ID по необходимости
]

# Состояния для ConversationHandler
(
    ADD_STUDENT_NUMBER,
    ADD_STUDENT_NAME,
    ADD_STUDENT_SURNAME,
    ADD_STUDENT_PATRONYMIC,
    ADD_STUDENT_BIRTH_YEAR,
    ADD_STUDENT_STUDY_PLACE,
    ADD_STUDENT_PARENT_NUMBERS,
    ADD_STUDENT_PARENT_BIRTH_YEAR,
    ADD_STUDENT_PARENT_NAMES,
    ADD_STUDENT_PARENT_WORK_PLACES,
    ADD_STUDENT_LOCATION,
    ADD_STUDENT_PHOTO,
    ADD_STUDENT_PARENT_PHOTO,
    SEARCH_STUDENT_NUMBER,
) = range(14)

# Инициализация базы данных
def init_db():
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()

    # Таблица учеников
    c.execute('''
        CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_number INTEGER UNIQUE,
            photo BLOB,
            first_name TEXT,
            last_name TEXT,
            patronymic TEXT,
            birth_year INTEGER,
            student_study_place TEXT,
            parent_numbers TEXT,
            parent_birth_year TEXT,  -- Изменено с INTEGER на TEXT
            parent_names TEXT,
            parent_work_places TEXT,
            parent_photos BLOB,
            parent_location_lat REAL,
            parent_location_lon REAL,
            qr_code BLOB
        )
    ''')

    # Таблица учителей
    c.execute('''
        CREATE TABLE IF NOT EXISTS teachers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER UNIQUE
        )
    ''')

    # Добавление первоначальных администраторов
    for admin_id in INITIAL_ADMIN_IDS:
        try:
            c.execute("INSERT OR IGNORE INTO teachers (user_id) VALUES (?)", (admin_id,))
        except Exception as e:
            logger.error(f"Ошибка при добавлении админа {admin_id}: {e}")

    conn.commit()
    conn.close()

# Проверка, является ли пользователь учителем
def is_teacher(user_id):
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute("SELECT * FROM teachers WHERE user_id = ?", (user_id,))
    result = c.fetchone()
    conn.close()
    return result is not None

# Главное меню
def main_menu(update: Update, context: CallbackContext):
    user = update.effective_user
    buttons = [
        [KeyboardButton("🔍 Поиск ученика по номеру")],
        [KeyboardButton("📸 Сканировать QR-код")],
    ]
    if is_teacher(user.id):
        buttons.append([KeyboardButton("⚙️ Административные функции")])
    reply_markup = ReplyKeyboardMarkup(buttons, resize_keyboard=True, one_time_keyboard=True)
    update.message.reply_text(
        f"👋 Здравствуйте, {user.first_name}! Выберите действие:", reply_markup=reply_markup
    )

# Добавление учителя через команду /add_teacher <user_id>
def add_teacher_command(update: Update, context: CallbackContext):
    if not is_teacher(update.effective_user.id):
        update.message.reply_text("❌ У вас нет прав для выполнения этой команды.")
        return
    if len(context.args) != 1:
        update.message.reply_text("ℹ️ Использование: /add_teacher <user_id>")
        return
    try:
        user_id = int(context.args[0])
    except ValueError:
        update.message.reply_text("❌ Пожалуйста, предоставьте действительный Telegram ID.")
        return
    try:
        conn = sqlite3.connect(DATABASE)
        c = conn.cursor()
        c.execute("INSERT INTO teachers (user_id) VALUES (?)", (user_id,))
        conn.commit()
        conn.close()
        update.message.reply_text(f"✅ Учитель с Telegram ID {user_id} добавлен.")
    except sqlite3.IntegrityError:
        update.message.reply_text("⚠️ Этот пользователь уже является учителем.")
    except Exception as e:
        logger.error(e)
        update.message.reply_text("❌ Произошла ошибка при добавлении учителя.")

# Удаление учителя через команду /delete_teacher <user_id>
def delete_teacher_command(update: Update, context: CallbackContext):
    if not is_teacher(update.effective_user.id):
        update.message.reply_text("❌ У вас нет прав для выполнения этой команды.")
        return
    if len(context.args) != 1:
        update.message.reply_text("ℹ️ Использование: /delete_teacher <user_id>")
        return
    try:
        user_id = int(context.args[0])
    except ValueError:
        update.message.reply_text("❌ Пожалуйста, предоставьте действительный Telegram ID.")
        return
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute("DELETE FROM teachers WHERE user_id = ?", (user_id,))
    if c.rowcount == 0:
        update.message.reply_text("⚠️ Учитель с таким Telegram ID не найден.")
    else:
        update.message.reply_text(f"✅ Учитель с Telegram ID {user_id} удален.")
    conn.commit()
    conn.close()

# Добавление ученика (ConversationHandler)
def add_student_start(update: Update, context: CallbackContext):
    if not is_teacher(update.effective_user.id):
        update.message.reply_text("❌ У вас нет прав для выполнения этой команды.")
        return ConversationHandler.END
    # Главное меню кнопки для отмены и возврата
    buttons = [
        [KeyboardButton("❌ Отмена"), KeyboardButton("🔙 Вернуться в главное меню")]
    ]
    reply_markup = ReplyKeyboardMarkup(buttons, resize_keyboard=True, one_time_keyboard=True)
    update.message.reply_text(
        "📋 Введите номер ученика или используйте кнопки ниже:",
        reply_markup=reply_markup
    )
    return ADD_STUDENT_NUMBER

def add_student_number(update: Update, context: CallbackContext):
    text = update.message.text.lower()
    if text in ["❌ отмена", "🔙 вернуться в главное меню"]:
        return handle_back_or_cancel(update, context)
    student_number = update.message.text.strip()
    if not student_number.isdigit():
        update.message.reply_text("❌ Номер ученика должен состоять только из цифр. Пожалуйста, повторите ввод:")
        return ADD_STUDENT_NUMBER
    context.user_data['student_number'] = int(student_number)
    # Кнопки для отмены и возврата
    buttons = [
        [KeyboardButton("❌ Отмена"), KeyboardButton("🔙 Вернуться в главное меню")]
    ]
    reply_markup = ReplyKeyboardMarkup(buttons, resize_keyboard=True, one_time_keyboard=True)
    update.message.reply_text("👤 Введите имя ученика:", reply_markup=reply_markup)
    return ADD_STUDENT_NAME

def add_student_name(update: Update, context: CallbackContext):
    text = update.message.text.lower()
    if text in ["❌ отмена", "🔙 вернуться в главное меню"]:
        return handle_back_or_cancel(update, context)
    first_name = update.message.text.strip()
    if not first_name:
        update.message.reply_text("❌ Имя не может быть пустым. Пожалуйста, введите имя ученика:")
        return ADD_STUDENT_NAME
    context.user_data['first_name'] = first_name
    buttons = [
        [KeyboardButton("❌ Отмена"), KeyboardButton("🔙 Вернуться в главное меню")]
    ]
    reply_markup = ReplyKeyboardMarkup(buttons, resize_keyboard=True, one_time_keyboard=True)
    update.message.reply_text("📛 Введите фамилию ученика:", reply_markup=reply_markup)
    return ADD_STUDENT_SURNAME

def add_student_surname(update: Update, context: CallbackContext):
    text = update.message.text.lower()
    if text in ["❌ отмена", "🔙 вернуться в главное меню"]:
        return handle_back_or_cancel(update, context)
    last_name = update.message.text.strip()
    if not last_name:
        update.message.reply_text("❌ Фамилия не может быть пустой. Пожалуйста, введите фамилию ученика:")
        return ADD_STUDENT_SURNAME
    context.user_data['last_name'] = last_name
    buttons = [
        [KeyboardButton("❌ Отмена"), KeyboardButton("🔙 Вернуться в главное меню")]
    ]
    reply_markup = ReplyKeyboardMarkup(buttons, resize_keyboard=True, one_time_keyboard=True)
    update.message.reply_text("🆔 Введите отчество ученика:", reply_markup=reply_markup)
    return ADD_STUDENT_PATRONYMIC

def add_student_patronymic(update: Update, context: CallbackContext):
    text = update.message.text.lower()
    if text in ["❌ отмена", "🔙 вернуться в главное меню"]:
        return handle_back_or_cancel(update, context)
    patronymic = update.message.text.strip()
    context.user_data['patronymic'] = patronymic
    buttons = [
        [KeyboardButton("❌ Отмена"), KeyboardButton("🔙 Вернуться в главное меню")]
    ]
    reply_markup = ReplyKeyboardMarkup(buttons, resize_keyboard=True, one_time_keyboard=True)
    update.message.reply_text("📅 Введите год рождения ученика (например, 2005):", reply_markup=reply_markup)
    return ADD_STUDENT_BIRTH_YEAR

def add_student_birth_year(update: Update, context: CallbackContext):
    text = update.message.text.lower()
    if text in ["❌ отмена", "🔙 вернуться в главное меню"]:
        return handle_back_or_cancel(update, context)
    birth_year = update.message.text.strip()
    current_year = datetime.now().year
    if not birth_year.isdigit() or not (1900 <= int(birth_year) <= current_year):
        update.message.reply_text("❌ Пожалуйста, введите действительный год рождения (например, 2005):")
        return ADD_STUDENT_BIRTH_YEAR
    context.user_data['birth_year'] = int(birth_year)
    buttons = [
        [KeyboardButton("❌ Отмена"), KeyboardButton("🔙 Вернуться в главное меню")]
    ]
    reply_markup = ReplyKeyboardMarkup(buttons, resize_keyboard=True, one_time_keyboard=True)
    update.message.reply_text("🏫 Введите место учебы ученика:", reply_markup=reply_markup)
    return ADD_STUDENT_STUDY_PLACE

def add_student_study_place(update: Update, context: CallbackContext):
    text = update.message.text.lower()
    if text in ["❌ отмена", "🔙 вернуться в главное меню"]:
        return handle_back_or_cancel(update, context)
    study_place = update.message.text.strip()
    if not study_place:
        update.message.reply_text("❌ Место учебы не может быть пустым. Пожалуйста, введите место учебы ученика:")
        return ADD_STUDENT_STUDY_PLACE
    context.user_data['study_place'] = study_place
    buttons = [
        [KeyboardButton("❌ Отмена"), KeyboardButton("🔙 Вернуться в главное меню")]
    ]
    reply_markup = ReplyKeyboardMarkup(buttons, resize_keyboard=True, one_time_keyboard=True)
    update.message.reply_text("📞 Введите номера телефонов родителей (через запятую):", reply_markup=reply_markup)
    return ADD_STUDENT_PARENT_NUMBERS

def add_student_parent_numbers(update: Update, context: CallbackContext):
    text = update.message.text.lower()
    if text in ["❌ отмена", "🔙 вернуться в главное меню"]:
        return handle_back_or_cancel(update, context)
    parent_numbers = update.message.text.strip()
    if not parent_numbers:
        update.message.reply_text("❌ Номера телефонов не могут быть пустыми. Введите номера телефонов родителей:")
        return ADD_STUDENT_PARENT_NUMBERS
    # Дополнительная валидация номеров телефонов может быть добавлена здесь
    context.user_data['parent_numbers'] = parent_numbers
    buttons = [
        [KeyboardButton("❌ Отмена"), KeyboardButton("🔙 Вернуться в главное меню")]
    ]
    reply_markup = ReplyKeyboardMarkup(buttons, resize_keyboard=True, one_time_keyboard=True)
    update.message.reply_text(
        "📅 Введите дату рождения родителей (год или формат dd.mm.yyyy):",
        reply_markup=reply_markup
    )
    return ADD_STUDENT_PARENT_BIRTH_YEAR

def add_student_parent_birth_year(update: Update, context: CallbackContext):
    text = update.message.text.lower()
    if text in ["❌ отмена", "🔙 вернуться в главное меню"]:
        return handle_back_or_cancel(update, context)
    parent_birth_year = update.message.text.strip()
    # Проверяем, является ли ввод годом или датой
    year_regex = re.compile(r'^\d{4}$')
    date_regex = re.compile(r'^\d{2}\.\d{2}\.\d{4}$')
    if year_regex.match(parent_birth_year):
        # Ввод только года
        year = int(parent_birth_year)
        current_year = datetime.now().year
        if not (1900 <= year <= current_year):
            update.message.reply_text("❌ Пожалуйста, введите действительный год рождения (например, 1980):")
            return ADD_STUDENT_PARENT_BIRTH_YEAR
        formatted_birth_year = parent_birth_year  # Храним как есть
    elif date_regex.match(parent_birth_year):
        # Ввод полной даты
        try:
            date_obj = datetime.strptime(parent_birth_year, '%d.%m.%Y')
            formatted_birth_year = parent_birth_year  # Можно изменить формат хранения при необходимости
        except ValueError:
            update.message.reply_text("❌ Некорректный формат даты. Пожалуйста, используйте dd.mm.yyyy (например, 11.04.1988):")
            return ADD_STUDENT_PARENT_BIRTH_YEAR
    else:
        update.message.reply_text("❌ Некорректный формат. Введите только год (например, 1980) или дату в формате dd.mm.yyyy (например, 11.04.1988):")
        return ADD_STUDENT_PARENT_BIRTH_YEAR

    context.user_data['parent_birth_year'] = formatted_birth_year
    buttons = [
        [KeyboardButton("❌ Отмена"), KeyboardButton("🔙 Вернуться в главное меню")]
    ]
    reply_markup = ReplyKeyboardMarkup(buttons, resize_keyboard=True, one_time_keyboard=True)
    update.message.reply_text("👨‍👩‍👧 Введите имена родителей (через запятую):", reply_markup=reply_markup)
    return ADD_STUDENT_PARENT_NAMES

def add_student_parent_names(update: Update, context: CallbackContext):
    text = update.message.text.lower()
    if text in ["❌ отмена", "🔙 вернуться в главное меню"]:
        return handle_back_or_cancel(update, context)
    parent_names = update.message.text.strip()
    if not parent_names:
        update.message.reply_text("❌ Имена родителей не могут быть пустыми. Введите имена родителей:")
        return ADD_STUDENT_PARENT_NAMES
    context.user_data['parent_names'] = parent_names
    buttons = [
        [KeyboardButton("❌ Отмена"), KeyboardButton("🔙 Вернуться в главное меню")]
    ]
    reply_markup = ReplyKeyboardMarkup(buttons, resize_keyboard=True, one_time_keyboard=True)
    update.message.reply_text("💼 Введите места работы родителей (через запятую):", reply_markup=reply_markup)
    return ADD_STUDENT_PARENT_WORK_PLACES

def add_student_parent_work_places(update: Update, context: CallbackContext):
    text = update.message.text.lower()
    if text in ["❌ отмена", "🔙 вернуться в главное меню"]:
        return handle_back_or_cancel(update, context)
    parent_work_places = update.message.text.strip()
    if not parent_work_places:
        update.message.reply_text("❌ Места работы родителей не могут быть пустыми. Введите места работы родителей:")
        return ADD_STUDENT_PARENT_WORK_PLACES
    context.user_data['parent_work_places'] = parent_work_places
    # Добавляем кнопку для отправки локации
    buttons = [
        [KeyboardButton("📍 Отправить локацию", request_location=True)],
        [KeyboardButton("❌ Отмена"), KeyboardButton("🔙 Вернуться в главное меню")]
    ]
    reply_markup = ReplyKeyboardMarkup(buttons, resize_keyboard=True, one_time_keyboard=True)
    update.message.reply_text("📍 Отправьте локацию родителей:", reply_markup=reply_markup)
    return ADD_STUDENT_LOCATION

def add_student_location(update: Update, context: CallbackContext):
    text = update.message.text.lower() if update.message.text else ""
    if text in ["❌ отмена", "🔙 вернуться в главное меню"]:
        return handle_back_or_cancel(update, context)
    if update.message.location:
        location = update.message.location
        context.user_data['parent_location_lat'] = location.latitude
        context.user_data['parent_location_lon'] = location.longitude
        logger.info(f"Получена локация: {location.latitude}, {location.longitude}")
        buttons = [
            [KeyboardButton("❌ Отмена"), KeyboardButton("🔙 Вернуться в главное меню")]
        ]
        reply_markup = ReplyKeyboardMarkup(buttons, resize_keyboard=True, one_time_keyboard=True)
        update.message.reply_text("📸 Отправьте фото ученика:", reply_markup=reply_markup)
        return ADD_STUDENT_PHOTO
    else:
        update.message.reply_text("❌ Пожалуйста, отправьте действительную локацию через кнопку или вручную.")
        return ADD_STUDENT_LOCATION

def add_student_photo(update: Update, context: CallbackContext):
    text = update.message.text.lower() if update.message.text else ""
    if text in ["❌ отмена", "🔙 вернуться в главное меню"]:
        return handle_back_or_cancel(update, context)
    if update.message.photo:
        photo = update.message.photo[-1].get_file()
        photo_bytes = photo.download_as_bytearray()
        context.user_data['photo'] = photo_bytes
        buttons = [
            [KeyboardButton("❌ Отмена"), KeyboardButton("🔙 Вернуться в главное меню")]
        ]
        reply_markup = ReplyKeyboardMarkup(buttons, resize_keyboard=True, one_time_keyboard=True)
        update.message.reply_text("📸 Отправьте фото родителей:", reply_markup=reply_markup)
        return ADD_STUDENT_PARENT_PHOTO
    else:
        update.message.reply_text("❌ Пожалуйста, отправьте фотографию ученика:")
        return ADD_STUDENT_PHOTO

def add_student_parent_photo(update: Update, context: CallbackContext):
    text = update.message.text.lower() if update.message.text else ""
    if text in ["❌ отмена", "🔙 вернуться в главное меню"]:
        return handle_back_or_cancel(update, context)
    if update.message.photo:
        parent_photo = update.message.photo[-1].get_file()
        parent_photo_bytes = parent_photo.download_as_bytearray()
        context.user_data['parent_photos'] = parent_photo_bytes
        logger.info("Получена фотография родителей.")
        # Сохраним данные в базу
        try:
            conn = sqlite3.connect(DATABASE)
            c = conn.cursor()
            student_number = context.user_data['student_number']
            first_name = context.user_data['first_name']
            last_name = context.user_data['last_name']
            patronymic = context.user_data['patronymic']
            birth_year = context.user_data['birth_year']
            study_place = context.user_data['study_place']
            parent_numbers = context.user_data['parent_numbers']
            parent_birth_year = context.user_data['parent_birth_year']
            parent_names = context.user_data['parent_names']
            parent_work_places = context.user_data['parent_work_places']
            parent_location_lat = context.user_data['parent_location_lat']
            parent_location_lon = context.user_data['parent_location_lon']
            photo = context.user_data['photo']
            parent_photos = context.user_data['parent_photos']

            # Генерация QR-кода с глубокими ссылками
            deep_link = f"https://t.me/{BOT_USERNAME}?start={student_number}"
            qr = qrcode.QRCode(version=1, box_size=10, border=5)
            qr.add_data(deep_link)
            qr.make(fit=True)
            img = qr.make_image(fill='black', back_color='white')
            buf = BytesIO()
            img.save(buf, format='PNG')
            qr_code = buf.getvalue()

            c.execute('''
                INSERT INTO students (
                    student_number, photo, first_name, last_name, patronymic, 
                    birth_year, student_study_place, parent_numbers, parent_birth_year,
                    parent_names, parent_work_places, parent_photos, 
                    parent_location_lat, parent_location_lon, qr_code
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                student_number,
                photo,
                first_name,
                last_name,
                patronymic,
                birth_year,
                study_place,
                parent_numbers,
                parent_birth_year,
                parent_names,
                parent_work_places,
                parent_photos,
                parent_location_lat,
                parent_location_lon,
                qr_code
            ))
            conn.commit()
            conn.close()
            update.message.reply_text("✅ Ученик успешно добавлен.", reply_markup=ReplyKeyboardRemove())
            logger.info(f"Ученик с номером {student_number} добавлен в базу данных.")
        except sqlite3.IntegrityError:
            update.message.reply_text("⚠️ Ученик с таким номером уже существует.", reply_markup=ReplyKeyboardRemove())
            logger.warning(f"Попытка добавить существующего ученика с номером {student_number}.")
        except Exception as e:
            logger.error(f"Ошибка при добавлении ученика: {e}")
            update.message.reply_text("❌ Произошла ошибка при добавлении ученика. Пожалуйста, попробуйте снова.", reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END
    else:
        update.message.reply_text("❌ Пожалуйста, отправьте фотографию родителей или используйте кнопки ниже.")
        return ADD_STUDENT_PARENT_PHOTO

def add_student_cancel(update: Update, context: CallbackContext):
    update.message.reply_text("❌ Добавление ученика отменено.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

def handle_back_or_cancel(update: Update, context: CallbackContext):
    user = update.effective_user
    buttons = [
        [KeyboardButton("🔍 Поиск ученика по номеру")],
        [KeyboardButton("📸 Сканировать QR-код")],
    ]
    if is_teacher(user.id):
        buttons.append([KeyboardButton("⚙️ Административные функции")])
    reply_markup = ReplyKeyboardMarkup(buttons, resize_keyboard=True, one_time_keyboard=True)
    update.message.reply_text("👋 Вы вернулись в главное меню.", reply_markup=reply_markup)
    return ConversationHandler.END

# Удаление ученика через команду /delete_student <student_number>
def delete_student_command(update: Update, context: CallbackContext):
    if not is_teacher(update.effective_user.id):
        update.message.reply_text("❌ У вас нет прав для выполнения этой команды.")
        return
    if len(context.args) != 1:
        update.message.reply_text("ℹ️ Использование: /delete_student <student_number>")
        return
    student_number = context.args[0]
    if not student_number.isdigit():
        update.message.reply_text("❌ Номер ученика должен состоять только из цифр.")
        return
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute("DELETE FROM students WHERE student_number = ?", (int(student_number),))
    if c.rowcount == 0:
        update.message.reply_text("⚠️ Ученик с таким номером не найден.")
    else:
        update.message.reply_text(f"✅ Ученик с номером {student_number} удален.")
    conn.commit()
    conn.close()

# Получение QR-кода ученика по номеру через команду /get_qr <student_number>
def get_qr_code_command(update: Update, context: CallbackContext):
    if not is_teacher(update.effective_user.id):
        update.message.reply_text("❌ У вас нет прав для выполнения этой команды.")
        return
    if len(context.args) != 1:
        update.message.reply_text("ℹ️ Использование: /get_qr <student_number>")
        return
    student_number = context.args[0]
    if not student_number.isdigit():
        update.message.reply_text("❌ Номер ученика должен состоять только из цифр.")
        return
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute("SELECT qr_code FROM students WHERE student_number = ?", (int(student_number),))
    result = c.fetchone()
    conn.close()
    if result and result[0]:
        qr_code = result[0]
        bot_photo = BytesIO(qr_code)
        bot_photo.name = 'qr_code.png'
        update.message.reply_photo(photo=bot_photo, caption=f"📄 QR-код для ученика с номером {student_number}.")
        logger.info(f"Отправлен QR-код ученика с номером {student_number}.")
    else:
        update.message.reply_text("⚠️ QR-код для этого ученика не найден.")
        logger.warning(f"QR-код для ученика с номером {student_number} не найден.")

# Просмотр данных ученика по номеру (ConversationHandler)
def search_student_start(update: Update, context: CallbackContext):
    buttons = [
        [KeyboardButton("❌ Отмена"), KeyboardButton("🔙 Вернуться в главное меню")]
    ]
    reply_markup = ReplyKeyboardMarkup(buttons, resize_keyboard=True, one_time_keyboard=True)
    update.message.reply_text(
        "🔍 Введите номер ученика для поиска или используйте кнопки ниже:",
        reply_markup=reply_markup
    )
    return SEARCH_STUDENT_NUMBER

def search_student_number(update: Update, context: CallbackContext):
    text = update.message.text.lower() if update.message.text else ""
    if text in ["❌ отмена", "🔙 вернуться в главное меню"]:
        user = update.effective_user
        buttons = [
            [KeyboardButton("🔍 Поиск ученика по номеру")],
            [KeyboardButton("📸 Сканировать QR-код")],
        ]
        if is_teacher(user.id):
            buttons.append([KeyboardButton("⚙️ Административные функции")])
        reply_markup = ReplyKeyboardMarkup(buttons, resize_keyboard=True, one_time_keyboard=True)
        update.message.reply_text("👋 Вы вернулись в главное меню.", reply_markup=reply_markup)
        return ConversationHandler.END

    student_number = update.message.text.strip()
    if not student_number.isdigit():
        update.message.reply_text("❌ Номер ученика должен состоять только из цифр. Пожалуйста, повторите ввод:")
        return SEARCH_STUDENT_NUMBER
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute("SELECT * FROM students WHERE student_number = ?", (int(student_number),))
    student = c.fetchone()
    conn.close()
    if student:
        (
            id,
            student_number,
            photo,
            first_name,
            last_name,
            patronymic,
            birth_year,
            study_place,
            parent_numbers,
            parent_birth_year,
            parent_names,
            parent_work_places,
            parent_photos,
            parent_location_lat,
            parent_location_lon,
            qr_code,
        ) = student
        # Отправляем фото ученика
        if photo:
            bot_photo = BytesIO(photo)
            bot_photo.name = 'student_photo.jpg'
            update.message.reply_photo(photo=bot_photo)
        # Отправляем фото родителей, если есть
        if parent_photos:
            bot_parent_photo = BytesIO(parent_photos)
            bot_parent_photo.name = 'parent_photos.jpg'
            update.message.reply_photo(photo=bot_parent_photo, caption="📸 Фотография родителей:")
        # Отправляем информацию
        info = (
            f"📄 **Информация об ученике**\n"
            f"**Номер ученика:** {student_number}\n"
            f"**Имя:** {first_name}\n"
            f"**Фамилия:** {last_name}\n"
            f"**Отчество:** {patronymic}\n"
            f"**Год рождения:** {birth_year}\n"
            f"**Место учебы:** {study_place}\n"
            f"**Номера родителей:** {parent_numbers}\n"
            f"**Дата рождения родителей:** {parent_birth_year}\n"
            f"**Имена родителей:** {parent_names}\n"
            f"**Места работы родителей:** {parent_work_places}\n"
        )
        update.message.reply_text(info, parse_mode=ParseMode.MARKDOWN)
        # Отправляем локацию
        if parent_location_lat and parent_location_lon:
            update.message.reply_location(latitude=parent_location_lat, longitude=parent_location_lon)
        else:
            update.message.reply_text("❌ Местоположение родителей недоступно.")
        logger.info(f"Информация о студенте с номером {student_number} отправлена.")
    else:
        update.message.reply_text("⚠️ Ученик с таким номером не найден.")
        logger.warning(f"Студент с номером {student_number} не найден.")
    return ConversationHandler.END

# Обработка QR-кода фотографии
def handle_photo(update: Update, context: CallbackContext):
    photo_file = update.message.photo[-1].get_file()
    photo_bytes = photo_file.download_as_bytearray()
    try:
        img = Image.open(BytesIO(photo_bytes))
    except Exception as e:
        logger.error(f"Ошибка при открытии изображения: {e}")
        update.message.reply_text("❌ Не удалось открыть изображение. Пожалуйста, попробуйте снова.")
        return
    decoded = decode(img)
    if decoded:
        data = decoded[0].data.decode('utf-8')
        if data.startswith(f"https://t.me/{BOT_USERNAME}?start="):
            # Извлекаем номер ученика из глубокой ссылки
            student_number = data.split('start=')[-1]
            if student_number.isdigit():
                logger.info(f"Обработка QR-кода с номером ученика: {student_number}")
                conn = sqlite3.connect(DATABASE)
                c = conn.cursor()
                c.execute("SELECT * FROM students WHERE student_number = ?", (int(student_number),))
                student = c.fetchone()
                conn.close()
                if student:
                    (
                        id,
                        student_number,
                        photo,
                        first_name,
                        last_name,
                        patronymic,
                        birth_year,
                        study_place,
                        parent_numbers,
                        parent_birth_year,
                        parent_names,
                        parent_work_places,
                        parent_photos,
                        parent_location_lat,
                        parent_location_lon,
                        qr_code,
                    ) = student
                    # Отправляем фото ученика
                    if photo:
                        bot_photo = BytesIO(photo)
                        bot_photo.name = 'student_photo.jpg'
                        update.message.reply_photo(photo=bot_photo)
                    # Отправляем фото родителей, если есть
                    if parent_photos:
                        bot_parent_photo = BytesIO(parent_photos)
                        bot_parent_photo.name = 'parent_photos.jpg'
                        update.message.reply_photo(photo=bot_parent_photo, caption="📸 Фотография родителей:")
                    # Отправляем информацию
                    info = (
                        f"📄 **Информация об ученике**\n"
                        f"**Номер ученика:** {student_number}\n"
                        f"**Имя:** {first_name}\n"
                        f"**Фамилия:** {last_name}\n"
                        f"**Отчество:** {patronymic}\n"
                        f"**Год рождения:** {birth_year}\n"
                        f"**Место учебы:** {study_place}\n"
                        f"**Номера родителей:** {parent_numbers}\n"
                        f"**Дата рождения родителей:** {parent_birth_year}\n"
                        f"**Имена родителей:** {parent_names}\n"
                        f"**Места работы родителей:** {parent_work_places}\n"
                    )
                    update.message.reply_text(info, parse_mode=ParseMode.MARKDOWN)
                    # Отправляем локацию
                    if parent_location_lat and parent_location_lon:
                        update.message.reply_location(latitude=parent_location_lat, longitude=parent_location_lon)
                    else:
                        update.message.reply_text("❌ Местоположение родителей недоступно.")
                    logger.info(f"Информация о студенте с номером {student_number} отправлена по QR-коду.")
                else:
                    update.message.reply_text("⚠️ Ученик с таким номером не найден.")
                    logger.warning(f"Студент с номером {student_number} не найден по QR-коду.")
            else:
                update.message.reply_text("❌ QR-код содержит некорректный номер ученика.")
                logger.warning("QR-код содержит некорректный номер ученика.")
        else:
            # Предполагается, что QR-код содержит только номер ученика
            if data.isdigit():
                student_number = int(data)
                logger.info(f"Обработка QR-кода с номером ученика: {student_number}")
                conn = sqlite3.connect(DATABASE)
                c = conn.cursor()
                c.execute("SELECT * FROM students WHERE student_number = ?", (student_number,))
                student = c.fetchone()
                conn.close()
                if student:
                    (
                        id,
                        student_number,
                        photo,
                        first_name,
                        last_name,
                        patronymic,
                        birth_year,
                        study_place,
                        parent_numbers,
                        parent_birth_year,
                        parent_names,
                        parent_work_places,
                        parent_photos,
                        parent_location_lat,
                        parent_location_lon,
                        qr_code,
                    ) = student
                    # Отправляем фото ученика
                    if photo:
                        bot_photo = BytesIO(photo)
                        bot_photo.name = 'student_photo.jpg'
                        update.message.reply_photo(photo=bot_photo)
                    # Отправляем фото родителей, если есть
                    if parent_photos:
                        bot_parent_photo = BytesIO(parent_photos)
                        bot_parent_photo.name = 'parent_photos.jpg'
                        update.message.reply_photo(photo=bot_parent_photo, caption="📸 Фотография родителей:")
                    # Отправляем информацию
                    info = (
                        f"📄 **Информация об ученике**\n"
                        f"**Номер ученика:** {student_number}\n"
                        f"**Имя:** {first_name}\n"
                        f"**Фамилия:** {last_name}\n"
                        f"**Отчество:** {patronymic}\n"
                        f"**Год рождения:** {birth_year}\n"
                        f"**Место учебы:** {study_place}\n"
                        f"**Номера родителей:** {parent_numbers}\n"
                        f"**Дата рождения родителей:** {parent_birth_year}\n"
                        f"**Имена родителей:** {parent_names}\n"
                        f"**Места работы родителей:** {parent_work_places}\n"
                    )
                    update.message.reply_text(info, parse_mode=ParseMode.MARKDOWN)
                    # Отправляем локацию
                    if parent_location_lat and parent_location_lon:
                        update.message.reply_location(latitude=parent_location_lat, longitude=parent_location_lon)
                    else:
                        update.message.reply_text("❌ Местоположение родителей недоступно.")
                    logger.info(f"Информация о студенте с номером {student_number} отправлена по номеру телефона.")
                else:
                    update.message.reply_text("⚠️ Ученик с таким номером не найден.")
                    logger.warning(f"Студент с номером {student_number} не найден по номеру телефона.")
            else:
                update.message.reply_text("❌ QR-код не содержит действительный номер ученика.")
                logger.warning("QR-код не содержит действительный номер ученика.")
    else:
        update.message.reply_text("❌ QR-код не распознан. Пожалуйста, попробуйте снова.")
        logger.warning("QR-код не распознан.")

# Главная команда /start
def start(update: Update, context: CallbackContext):
    if context.args:
        # Обработка команды /start с параметром
        student_number = context.args[0]
        if student_number.isdigit():
            logger.info(f"Обработка команды /start с номером ученика: {student_number}")
            conn = sqlite3.connect(DATABASE)
            c = conn.cursor()
            c.execute("SELECT * FROM students WHERE student_number = ?", (int(student_number),))
            student = c.fetchone()
            conn.close()
            if student:
                (
                    id,
                    student_number,
                    photo,
                    first_name,
                    last_name,
                    patronymic,
                    birth_year,
                    study_place,
                    parent_numbers,
                    parent_birth_year,
                    parent_names,
                    parent_work_places,
                    parent_photos,
                    parent_location_lat,
                    parent_location_lon,
                    qr_code,
                ) = student
                # Отправляем фото ученика
                if photo:
                    bot_photo = BytesIO(photo)
                    bot_photo.name = 'student_photo.jpg'
                    update.message.reply_photo(photo=bot_photo)
                # Отправляем фото родителей, если есть
                if parent_photos:
                    bot_parent_photo = BytesIO(parent_photos)
                    bot_parent_photo.name = 'parent_photos.jpg'
                    update.message.reply_photo(photo=bot_parent_photo, caption="📸 Фотография родителей:")
                # Отправляем информацию
                info = (
                    f"📄 **Информация об ученике**\n"
                    f"**Номер ученика:** {student_number}\n"
                    f"**Имя:** {first_name}\n"
                    f"**Фамилия:** {last_name}\n"
                    f"**Отчество:** {patronymic}\n"
                    f"**Год рождения:** {birth_year}\n"
                    f"**Место учебы:** {study_place}\n"
                    f"**Номера родителей:** {parent_numbers}\n"
                    f"**Дата рождения родителей:** {parent_birth_year}\n"
                    f"**Имена родителей:** {parent_names}\n"
                    f"**Места работы родителей:** {parent_work_places}\n"
                )
                update.message.reply_text(info, parse_mode=ParseMode.MARKDOWN)
                # Отправляем локацию
                if parent_location_lat and parent_location_lon:
                    update.message.reply_location(latitude=parent_location_lat, longitude=parent_location_lon)
                else:
                    update.message.reply_text("❌ Местоположение родителей недоступно.")
                logger.info(f"Информация о студенте с номером {student_number} отправлена через /start.")
            else:
                update.message.reply_text("⚠️ Ученик с таким номером не найден.")
                logger.warning(f"Студент с номером {student_number} не найден при обработке команды /start.")
        else:
            update.message.reply_text("❌ Некорректный номер ученика в QR-коде.")
            logger.warning("Некорректный номер ученика в QR-коде при обработке команды /start.")
    else:
        # Без параметра - показать главное меню
        main_menu(update, context)  

# Обработка текстовых сообщений для навигации
def handle_text(update: Update, context: CallbackContext):
    text = update.message.text
    if text == "🔍 Поиск ученика по номеру":
        return search_student_start(update, context)
    elif text == "📸 Сканировать QR-код":
        update.message.reply_text("📷 Пожалуйста, отправьте изображение с QR-кодом.")
    elif text == "⚙️ Административные функции":
        if is_teacher(update.effective_user.id):
            buttons = [
                [KeyboardButton("/add_student")],
                [KeyboardButton("/delete_student"), KeyboardButton("/add_teacher")],
                [KeyboardButton("/delete_teacher")],
                [KeyboardButton("🔙 Вернуться в главное меню")]
            ]
            reply_markup = ReplyKeyboardMarkup(buttons, resize_keyboard=True)
            update.message.reply_text("⚙️ Выберите административную команду:", reply_markup=reply_markup)
        else:
            update.message.reply_text("❌ У вас нет доступа к административным функциям.")
    elif text == "🔙 Вернуться в главное меню":
        main_menu(update, context)
    else:
        update.message.reply_text("ℹ️ Пожалуйста, выберите доступную опцию из меню.")
        logger.info(f"Неизвестная команда: {text}")

# Обработка неизвестных команд
def unknown(update: Update, context: CallbackContext):
    update.message.reply_text("❌ Извините, я не понимаю эту команду.")
    logger.warning(f"Получена неизвестная команда: {update.message.text}")

# Основная функция запуска бота
def main():
    # Инициализация базы данных
    init_db()

    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher

    # Conversation handler для добавления ученика
    conv_handler_add_student = ConversationHandler(
        entry_points=[CommandHandler('add_student', add_student_start)],
        states={
            ADD_STUDENT_NUMBER: [MessageHandler(Filters.text & ~Filters.command, add_student_number)],
            ADD_STUDENT_NAME: [MessageHandler(Filters.text & ~Filters.command, add_student_name)],
            ADD_STUDENT_SURNAME: [MessageHandler(Filters.text & ~Filters.command, add_student_surname)],
            ADD_STUDENT_PATRONYMIC: [MessageHandler(Filters.text & ~Filters.command, add_student_patronymic)],
            ADD_STUDENT_BIRTH_YEAR: [MessageHandler(Filters.text & ~Filters.command, add_student_birth_year)],
            ADD_STUDENT_STUDY_PLACE: [MessageHandler(Filters.text & ~Filters.command, add_student_study_place)],
            ADD_STUDENT_PARENT_NUMBERS: [MessageHandler(Filters.text & ~Filters.command, add_student_parent_numbers)],
            ADD_STUDENT_PARENT_BIRTH_YEAR: [MessageHandler(Filters.text & ~Filters.command, add_student_parent_birth_year)],
            ADD_STUDENT_PARENT_NAMES: [MessageHandler(Filters.text & ~Filters.command, add_student_parent_names)],
            ADD_STUDENT_PARENT_WORK_PLACES: [MessageHandler(Filters.text & ~Filters.command, add_student_parent_work_places)],
            ADD_STUDENT_LOCATION: [MessageHandler((Filters.location) | (Filters.text & ~Filters.command), add_student_location)],
            ADD_STUDENT_PHOTO: [MessageHandler(Filters.photo | (Filters.text & ~Filters.command), add_student_photo)],
            ADD_STUDENT_PARENT_PHOTO: [MessageHandler(Filters.photo | (Filters.text & ~Filters.command), add_student_parent_photo)],
        },
        fallbacks=[CommandHandler('cancel', add_student_cancel)],
        allow_reentry=True
    )

    # Conversation handler для поиска ученика
    conv_handler_search_student = ConversationHandler(
        entry_points=[MessageHandler(Filters.regex('🔍 Поиск ученика по номеру'), search_student_start)],
        states={
            SEARCH_STUDENT_NUMBER: [MessageHandler(Filters.text & ~Filters.command, search_student_number)],
        },
        fallbacks=[CommandHandler('cancel', add_student_cancel)],
    )

    # Регистрация обработчиков
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(conv_handler_add_student)
    dp.add_handler(conv_handler_search_student)
    dp.add_handler(CommandHandler("add_teacher", add_teacher_command))
    dp.add_handler(CommandHandler("delete_teacher", delete_teacher_command))
    dp.add_handler(CommandHandler("delete_student", delete_student_command))
    dp.add_handler(CommandHandler("get_qr", get_qr_code_command))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_text))
    dp.add_handler(MessageHandler(Filters.photo, handle_photo))
    dp.add_handler(MessageHandler(Filters.command, unknown))

    # Запуск бота
    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()