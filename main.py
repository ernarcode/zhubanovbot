from aiogram import Bot, Dispatcher, types, F
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, FSInputFile
from aiogram.filters import Command, StateFilter
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
import logging
import asyncio
import sqlite3
from functools import lru_cache
from typing import Optional, Tuple, Dict, Any
from config import TOKEN
from datetime import datetime


# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Инициализация бота
bot = Bot(token=TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# Состояния FSM
class UserStates(StatesGroup):
    choose_language = State()
    main_menu = State()
    bachelor_menu = State()
    master_menu = State()
    doctoral_menu = State()
    program_selection = State()
    previous_state = State()
    searching = State()  # Добавлено состояние для поиска
    choosing_result = State()  # Состояние для выбора результата поиска
    feedback = State()

# Подключение к базе данных
def get_db_connection():
    conn = sqlite3.connect("university.db")
    conn.row_factory = sqlite3.Row  # Возвращать строки как словари
    return conn


def search_in_all_tables(keyword: str, limit: int = 10):
    """
    Ищет совпадения (case-insensitive) в button_name и text_info
    во всех четырёх таблицах и возвращает до limit результатов.
    """
    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # шаблон с %keyword%
    kw = f"%{keyword}%"

    sql = """
        SELECT 'bachelor_info' AS table_name, button_name, text_info, file_path
          FROM bachelor_info
         WHERE text_info   LIKE ? COLLATE NOCASE
            OR button_name LIKE ? COLLATE NOCASE
        UNION ALL
        SELECT 'master_info', button_name, text_info, file_path
          FROM master_info
         WHERE text_info   LIKE ? COLLATE NOCASE
            OR button_name LIKE ? COLLATE NOCASE
        UNION ALL
        SELECT 'doctoral_info', button_name, text_info, file_path
          FROM doctoral_info
         WHERE text_info   LIKE ? COLLATE NOCASE
            OR button_name LIKE ? COLLATE NOCASE
        UNION ALL
        SELECT 'main_info', button_name, text_info, file_path
          FROM main_info
         WHERE text_info   LIKE ? COLLATE NOCASE
            OR button_name LIKE ? COLLATE NOCASE
        LIMIT ?
    """

    # Параметры: для каждой таблицы — kw дважды, в конце — limit
    params = (kw, kw,  kw, kw,  kw, kw,  kw, kw,  limit)
    cur.execute(sql, params)
    rows = cur.fetchall()
    conn.close()

    return [
        {
            "table":       r["table_name"],
            "button_name": r["button_name"],
            "text_info":   r["text_info"],
            "file_path":   r["file_path"],
        }
        for r in rows
    ]



# Получение списка программ из b_programs
def get_programs(language='ru'):
    conn = get_db_connection()
    cursor = conn.cursor()
    if language == 'ru':
        cursor.execute("SELECT name_ru FROM faculties")
    else:
        cursor.execute("SELECT name FROM faculties")
    programs = [row[0] for row in cursor.fetchall()]
    conn.close()
    return programs


# Получение пути к файлу для программы
def get_program_file(faculty_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT file_path FROM b_programms WHERE faculty_id = ?", (faculty_id,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else None

def get_program_file_ru(faculty_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT file_path_ru FROM b_programms WHERE faculty_id = ?", (faculty_id,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else None

# Обработчик кнопки "Образовательные программы"
@dp.message(lambda message: message.text in ["🎓 Образовательные программы", "🎓 Білім бағдарламалары"])
async def show_programs(message: types.Message, state: FSMContext):
    data = await state.get_data()
    language = data.get("language", "ru")
    back_text = "🔙 Артқа" if language == "kk" else "🔙 Назад"
    
    # Выбираем правильные названия факультетов в зависимости от языка
    programs = get_programs(language)
    
    if programs:
        keyboard = ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text=prog)] for prog in programs] + [[KeyboardButton(text=back_text)]],
            resize_keyboard=True
        )
        text_msg = "Қажетті білім бағдарламасын таңдаңыз:" if language == "kk" else "Выберите образовательную программу:"
        await message.answer(text_msg, reply_markup=keyboard)
        await state.set_state(UserStates.program_selection)
    else:
        await message.answer("Нет доступных программ.")




# Обработчик выбора программы
@dp.message(lambda message: message.text in get_programs('ru') or message.text in get_programs('kk'))
async def send_program_file(message: types.Message, state: FSMContext):
    data = await state.get_data()
    language = data.get("language", "ru")

    # Определяем, по какому столбцу искать
    search_column = "name_ru" if language == "ru" else "name"
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(f"SELECT id FROM faculties WHERE {search_column} = ?", (message.text,))
    row = cursor.fetchone()
    conn.close()
    
    if not row:
        await message.answer("Факультет не найден в базе данных.")
        return
    
    faculty_id = row["id"]
    
    # Ищем файл для выбранного языка
    if language == "ru":
        file_path = get_program_file_ru(faculty_id)
    else:
        file_path = get_program_file(faculty_id)

    if file_path:
        try:
            await message.answer_document(types.FSInputFile(file_path))
        except Exception as e:
            logging.error(f"Ошибка отправки файла: {e}")
            await message.answer("Файл не найден.")
    else:
        await message.answer("Файл не найден в базе данных.")


# Кэшированный запрос к базе данных
@lru_cache(maxsize=32)
def get_info_from_db(table: str, button_name: str) -> Optional[Tuple[str, str]]:
    """Получение информации из базы данных с кэшированием"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(f"SELECT text_info, file_path FROM {table} WHERE button_name = ?", (button_name,))
        data = cursor.fetchone()
        conn.close()

        print(f"🔍 DEBUG: Запрос в БД для кнопки '{button_name}', результат: {data}")  # 👈 Проверка

        if data:
            return data['text_info'], data['file_path']
        return None
    except Exception as e:
        logger.error(f"Ошибка базы данных: {e}")
        return None


# Клавиатуры
def get_language_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🇰🇿 Қазақ"), KeyboardButton(text="🇷🇺 Русский")]
        ],
        resize_keyboard=True
    )

# Языковые клавиатуры (перемещены в специальный словарь)
KEYBOARDS = {
    "main_menu": {
        "kk": ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="🎓 Бакалавриат"), KeyboardButton(text="📖 Магистратура")],
                [KeyboardButton(text="🎓 Докторантура"), KeyboardButton(text="📜 Қабылдау ережелері")],
                [KeyboardButton(text="🧭 Кәсіби бағдар"), KeyboardButton(text="💰 Оқу ақысы")],
                [KeyboardButton(text="🌍 Тілді өзгерту"), KeyboardButton(text="🔍 Іздеу")],
                [KeyboardButton(text="🗺️ Қалай жетемін")],
                [KeyboardButton(text="❓ Жиі қойылатын сұрақтар")]
            ],
            resize_keyboard=True
        ),
        "ru": ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="🎓 Бакалавриат"), KeyboardButton(text="📖 Магистратура")],
                [KeyboardButton(text="🎓 Докторантура"), KeyboardButton(text="📜 Правила приема")],
                [KeyboardButton(text="🧭 Профориентация"), KeyboardButton(text="💰 Стоимость обучения")],
                [KeyboardButton(text="🌍 Сменить язык"), KeyboardButton(text="🔍 Поиск")],
                [KeyboardButton(text="🗺️ Как добраться")],
                [KeyboardButton(text="❓ Часто задаваемые вопросы")]
            ],
            resize_keyboard=True
        )
    },
    "bachelor_menu": {
        "kk": ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="📚 Мемлекеттік білім беру тапсырысы"), KeyboardButton(text="📝 ҰБТ")],
                [KeyboardButton(text="📅 Талапкердің күнтізбесі"), KeyboardButton(text="📄 Қажетті құжаттар")],
                [KeyboardButton(text="🎓 Білім бағдарламалары"), KeyboardButton(text="📖 Бейіндік пәндері")],
                [KeyboardButton(text="🧑‍🏫 'Педагогика ғылымдары' арнайы емтиханы"), KeyboardButton(text="🎭 Шығармашылық ББ")],
                [KeyboardButton(text="🔙 Артқа")]
            ],
            resize_keyboard=True
        ),
        "ru": ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="📚 Государственный образовательный заказ"), KeyboardButton(text="📝 ЕНТ")],
                [KeyboardButton(text="📅 Календарь абитуриента"), KeyboardButton(text="📄 Необходимые документы")],
                [KeyboardButton(text="🎓 Образовательные программы"), KeyboardButton(text="📖 Профильные предметы")],
                [KeyboardButton(text="🧑‍🏫 Спецэкзамен 'Педагогические науки'"), KeyboardButton(text="🎭 Творческие ОП")],
                [KeyboardButton(text="🔙 Назад")]
            ],
            resize_keyboard=True
        )
    },
    "master_menu" : {
        "kk": ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Мемлекеттік білім беру тапсырысы маг"), KeyboardButton(text="ББ")],
            [KeyboardButton(text="Қажетті құжаттар маг")],
            [KeyboardButton(text="Байланыс")],
            [KeyboardButton(text="🔙 Артқа")]
        ],
        resize_keyboard=True
    ),
    "ru": ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Государственный образовательный заказ маг"), KeyboardButton(text="ОП")],
            [KeyboardButton(text="Необходимые документы маг")],
            [KeyboardButton(text="Контакты")],
            [KeyboardButton(text="🔙 Назад")]
        ],
        resize_keyboard=True
    )
    },
    "doctoral_menu" : {
        "kk": ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="Докторантура Мемлекеттік білім беру тапсырысы"), KeyboardButton(text="Докторантура Білім бағдарламалары")],
                [KeyboardButton(text="Докторантура Қажетті құжаттар"), KeyboardButton(text="Докторантура Байланыс")],
                [KeyboardButton(text="Докторантура Түсу емтихандарының бағдарламалары")],
                [KeyboardButton(text="🔙 Артқа")]
            ],
            resize_keyboard=True
        ),
        "ru": ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="Докторантура Государственный образовательный заказ"), KeyboardButton(text="Докторантура Образовательные программы")],
                [KeyboardButton(text="Докторантура Необходимые документы"), KeyboardButton(text="Докторантура Контакты")],
                [KeyboardButton(text="Докторантура Программы вступительных экзаменов")],
                [KeyboardButton(text="🔙 Назад")]
            ],
            resize_keyboard=True
        )
    }
}
KEYBOARDS["main_menu"]["kk"].keyboard.append([KeyboardButton(text="📝 Кері байланыс")])
KEYBOARDS["main_menu"]["ru"].keyboard.append([KeyboardButton(text="📝 Обратная связь")])

# Локализация текста
MESSAGES = {
    "welcome": {
        "kk": "Қош келдіңіз! Тілді таңдаңыз:",
        "ru": "Добро пожаловать! Выберите язык:"
    },
    "language_selected": {
        "kk": "Тілді таңдадыңыз!",
        "ru": "Вы выбрали язык!"
    },
    "choose_section": {
        "kk": "Қажетті бөлімді таңдаңыз:",
        "ru": "Выберите нужный раздел:"
    },
    "back": {
        "kk": "Артқа",
        "ru": "Назад"
    },
    "file_not_found": {
        "kk": "Файл табылмады.",
        "ru": "Файл не найден."
    },
    "info_not_found": {
        "kk": "Ақпарат жоқ.",
        "ru": "Информация отсутствует."
    }
}

# Функция создания таблицы для обратной связи
def create_feedback_table():
    conn = sqlite3.connect('university.db')
    cursor = conn.cursor()
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS feedback (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        username TEXT,
        first_name TEXT,
        last_name TEXT,
        message TEXT,
        language TEXT,
        timestamp DATETIME
    )
    ''')
    conn.commit()
    conn.close()

# Добавьте вызов функции в main() перед запуском бота
create_feedback_table()

@dp.message(F.text.in_(["📝 Обратная связь", "📝 Кері байланыс"]))
async def start_feedback(message: types.Message, state: FSMContext):
    # 1) Детерминируем язык по тексту кнопки
    if message.text == "📝 Кері байланыс":
        lang = "kk"
    else:
        lang = "ru"
    # 2) Обновляем state, чтобы feedback-ответ потом тоже знал язык
    await state.update_data(language=lang)

    # 3) Локализованные приглашения к вводу
    feedback_messages = {
        "ru": "Пожалуйста, напишите ваши пожелания или предложения для улучшения бота. Ваше мнение очень важно!",
        "kk": "Ботты жақсарту үшін өз ұсыныстарыңызды немесе тілектеріңізді жазыңыз. Сіздің пікіріңіз өте маңызды!"
    }

    await message.answer(feedback_messages[lang])
    await state.set_state(UserStates.feedback)


# Обработчик сохранения обратной связи
@dp.message(StateFilter(UserStates.feedback))
async def save_feedback(message: types.Message, state: FSMContext):
    """Сохранение обратной связи в базе данных"""
    try:
        # Получаем данные пользователя
        user = message.from_user
        data = await state.get_data()
        language = data.get("language", "ru")
        
        # Подключение к базе данных
        conn = sqlite3.connect('university.db')
        cursor = conn.cursor()
        
        # Сохранение обратной связи
        cursor.execute('''
        INSERT INTO feedback 
        (user_id, username, first_name, last_name, message, language, timestamp) 
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (
            user.id, 
            user.username or "Не указан", 
            user.first_name or "Не указано", 
            user.last_name or "Не указано", 
            message.text, 
            language,
            datetime.now()
        ))
        
        conn.commit()
        conn.close()
        
        # Сообщения о успешной отправке
        success_messages = {
            "ru": "Спасибо за ваш отзыв! Мы обязательно рассмотрим ваши предложения.",
            "kk": "Пікіріңіз үшін рахмет! Сіздің ұсыныстарыңызды міндетті түрде қарастырамыз."
        }
        
        await message.answer(success_messages[language])
        await state.clear()
        
        # Возврат в главное меню
        await message.answer(
            get_message("choose_section", language), 
            reply_markup=KEYBOARDS["main_menu"][language]
        )
        
    except Exception as e:
        logger.error(f"Ошибка при сохранении обратной связи: {e}")
        await message.answer("Произошла ошибка при сохранении вашего сообщения. Попробуйте позже.")
        await state.clear()

# Если хотите добавить администраторский функционал просмотра отзывов (опционально)
def get_recent_feedbacks(limit=100):
    """Получение последних отзывов"""
    conn = sqlite3.connect('university.db')
    cursor = conn.cursor()
    cursor.execute('''
    SELECT id, username, message, language, timestamp 
    FROM feedback 
    ORDER BY timestamp DESC 
    LIMIT ?
    ''', (limit,))
    feedbacks = cursor.fetchall()
    conn.close()
    return feedbacks
# ─── FAQ: ПОКАЗ СПИСКА ВОПРОСОВ ───
@dp.message(F.text.in_(["❓ Часто задаваемые вопросы", "❓ Жиі қойылатын сұрақтар"]))
async def show_faq_menu(message: types.Message, state: FSMContext):
    # 1) Определяем язык сразу из текста кнопки и сохраняем в FSM
    lang = "kk" if message.text == "❓ Жиі қойылатын сұрақтар" else "ru"
    await state.update_data(language=lang)

    # 2) Забираем ВСЕ вопросы из таблицы faqs
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, question_ru, question_kk FROM faqs")
    rows = cur.fetchall()
    conn.close()

    # 3) Убираем старую Reply-клавиатуру
    await message.answer(
        "Жиі қойылатын сұрақтар:" if lang == "kk" else "Часто задаваемые вопросы:",
        reply_markup=ReplyKeyboardRemove()
    )

    # 4) Выводим полный нумерованный список текстом
    lines = []
    for idx, r in enumerate(rows, start=1):
        q = r["question_kk"] if lang == "kk" else r["question_ru"]
        lines.append(f"{idx}. {q}")
    await message.answer("\n".join(lines))

    # 5) Строим Inline-кнопки с цифрами 1…N и кнопкой «Назад»
    #    Собираем цифровые кнопки подряд
    num_buttons = [
        InlineKeyboardButton(text=str(i), callback_data=f"faq:{r['id']}")
        for i, r in enumerate(rows, start=1)
    ]
    # Разбиваем на строки по 3 кнопки
    inline_rows = [
        num_buttons[i : i + 3] for i in range(0, len(num_buttons), 3)
    ]
    # Добавляем внизу кнопку «Назад»
    back_text = "🔙 Артқа" if lang == "kk" else "🔙 Назад"
    inline_rows.append([InlineKeyboardButton(text=back_text, callback_data="faq_back")])

    kb = InlineKeyboardMarkup(inline_keyboard=inline_rows)

    prompt = (
        "Выберите номер вопроса или вернитесь назад:"
        if lang == "ru"
        else "Сұрақ нөмірін таңдаңыз немесе артқа оралыңыз:"
    )
    await message.answer(prompt, reply_markup=kb)


# ─── FAQ: ОБРАБОТКА ВЫБОРА ВОПРОСА ───
@dp.callback_query(lambda c: c.data and c.data.startswith("faq:"))
async def process_faq(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = data.get("language", "ru")
    qid = int(callback.data.split(":", 1)[1])

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT answer_ru, answer_kk FROM faqs WHERE id = ?", (qid,))
    row = cur.fetchone()
    conn.close()

    if row:
        answer = row["answer_kk"] if lang == "kk" else row["answer_ru"]
        await callback.message.answer(answer)
    else:
        await callback.message.answer(
            "❗ Сұрақ табылмады." if lang == "kk" else "❗ Вопрос не найден."
        )
    # чтобы убрать «часики» на кнопке
    await callback.answer()


# ─── FAQ: ОБРАТНЫЙ ВОЗВРАТ В ГЛАВНОЕ МЕНЮ ───
@dp.callback_query(lambda c: c.data == "faq_back")
async def faq_back(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = data.get("language", "ru")
    # сбрасываем FSM
    await state.clear()
    # отправляем главное меню
    await callback.message.answer(
        get_message("choose_section", lang),
        reply_markup=KEYBOARDS["main_menu"][lang]
    )
    await callback.answer()
# Вспомогательная функция для получения локализованного сообщения
def get_message(message_key: str, language: str) -> str:
    """Получение локализованного текста сообщения"""
    return MESSAGES.get(message_key, {}).get(language, MESSAGES[message_key]["ru"])

# Обработчики команд
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext) -> None:
    """Обработка команды /start"""
    await message.answer(
        f"{get_message('welcome', 'kk')} / {get_message('welcome', 'ru')}", 
        reply_markup=get_language_keyboard()
    )
    await state.set_state(UserStates.choose_language)

# Обработчик выбора языка
@dp.message(lambda message: message.text in ["🇰🇿 Қазақ", "🇷🇺 Русский"])
async def choose_language(message: types.Message, state: FSMContext) -> None:
    """Обработка выбора языка"""
    language = "kk" if message.text == "🇰🇿 Қазақ" else "ru"
    await state.update_data(language=language)
    await message.answer(
        get_message("language_selected", language), 
        reply_markup=KEYBOARDS["main_menu"][language]
    )
    await state.set_state(UserStates.main_menu)

# Универсальный обработчик меню
async def handle_menu_transition(
    message: types.Message, 
    state: FSMContext, 
    target_state: State,
    menu_type: str
) -> None:
    """Универсальный обработчик переходов между меню"""
    data = await state.get_data()
    language = data.get("language", "ru")
    
    await state.update_data(previous_state=await state.get_state())
    await message.answer(
        get_message("choose_section", language), 
        reply_markup=KEYBOARDS[menu_type][language]
    )
    await state.set_state(target_state)



# Обработчик для кнопки "Стоимость обучения" / "Оқу ақысы"
@dp.message(F.text.in_(["💰 Оқу ақысы", "💰 Стоимость обучения"]))
async def handle_tuition_fee(message: types.Message, state: FSMContext):
    """Обработка кнопки 'Стоимость обучения'"""
    data = await state.get_data()
    language = data.get("language", "ru")
    button_name = "💰 Оқу ақысы" if language == "kk" else "💰 Стоимость обучения"
    await send_info(message, state, "main_info")  # Используем таблицу main_info

# Обработчик для кнопки "Правила приема" / "Қабылдау ережелері"
@dp.message(F.text.in_(["📜 Қабылдау ережелері", "📜 Правила приема"]))
async def handle_admission_rules(message: types.Message, state: FSMContext):
    """Обработка кнопки 'Правила приема'"""
    data = await state.get_data()
    language = data.get("language", "ru")
    button_name = "📜 Қабылдау ережелері" if language == "kk" else "📜 Правила приема"
    await send_info(message, state, "main_info")  # Используем таблицу main_info


@dp.message(F.text.in_(["🧭 Кәсіби бағдар", "🧭 Профориентация"]))
async def handle_admission_rules(message: types.Message, state: FSMContext):
    """Обработка кнопки 'Правила приема'"""
    data = await state.get_data()
    language = data.get("language", "ru")
    button_name = "🧭 Кәсіби бағдар" if language == "kk" else "🧭 Профориентация"
    await send_info(message, state, "main_info")  # Используем таблицу main_info

# Обработчик меню бакалавриата
@dp.message(F.text == "🎓 Бакалавриат")
async def show_bachelor_menu(message: types.Message, state: FSMContext) -> None:
    """Обработка выбора меню бакалавриата"""
    logger.info("Запрошено меню бакалавриата")
    await handle_menu_transition(message, state, UserStates.bachelor_menu, "bachelor_menu")

# Добавьте обработчик для кнопки меню Магистратуры
@dp.message(F.text.in_(["📖 Магистратура"]))
async def show_master_menu(message: types.Message, state: FSMContext) -> None:
    """Обработка выбора меню магистратуры"""
    logger.info("Запрошено меню магистратуры")
    await handle_menu_transition(message, state, UserStates.master_menu, "master_menu")

# Обработчик меню докторантуры
@dp.message(F.text.in_(["🎓 Докторантура"]))
async def show_doctoral_menu(message: types.Message, state: FSMContext) -> None:
    """Обработка выбора меню докторантуры"""
    logger.info("Запрошено меню докторантуры")
    await handle_menu_transition(message, state, UserStates.doctoral_menu, "doctoral_menu")

#obrabotka info
async def send_info(message: types.Message, state: FSMContext, table: str) -> None:
    """Универсальный обработчик для отправки информации из базы данных"""
    logger.info(f"Запрошена информация: {message.text} из таблицы {table}")
    data = await state.get_data()
    language = data.get("language", "ru")
    msg = message.text  
    info = get_info_from_db(table, msg)
    
    if info:
        text, file_path = info
        await message.answer(text)
        
        if file_path:  # Проверяем, есть ли путь к файлу
            try:
                await message.answer_document(types.FSInputFile(file_path))
            except Exception as e:
                logger.error(f"Ошибка отправки файла: {e}")
                await message.answer(get_message("file_not_found", language))
        else:
            logger.warning(f"Файл не найден для кнопки: {msg}")
    else:
        await message.answer(get_message("info_not_found", language))
        

# ——— ХЭНДЛЕР СТАРТА ПОИСКА ———
@dp.message(F.text.in_(["🔍 Поиск", "🔍 Іздеу"]))
async def start_search(message: types.Message, state: FSMContext):
    # 1) Определяем язык по самому тексту кнопки
    if message.text == "🔍 Іздеу":
        lang = "kk"
    else:
        lang = "ru"
    # 2) Обновляем FSM-данные
    await state.update_data(language=lang)

    # 3) Готовим клавиатуру с кнопкой «Отмена» на нужном языке
    cancel = "❌ Болдырмау" if lang == "kk" else "❌ Отмена"
    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=cancel)]],
        resize_keyboard=True,
        one_time_keyboard=True
    )

    # 4) Локализованный prompt
    prompt = {
        "kk": f"Іздеу үшін кілт сөзді енгізіңіз немесе «{cancel}»:",
        "ru": f"Введите ключевое слово или «{cancel}»:"
    }[lang]

    await message.answer(prompt, reply_markup=kb)
    await state.set_state(UserStates.searching)


# ——— ХЭНДЛЕР ВВОДА КЛЮЧЕВОГО СЛОВА ———
@dp.message(StateFilter(UserStates.searching))
async def handle_search(message: types.Message, state: FSMContext):
    data = await state.get_data()
    lang = data["language"]  # уже точно 'ru' или 'kk'
    cancel = "❌ Болдырмау" if lang == "kk" else "❌ Отмена"
    text = message.text.strip()

    # Обработка «Отмена»
    if text == cancel:
        await state.clear()
        await message.answer(
            {"kk": "іздеу тоқтатылды.", "ru": "Поиск отменён."}[lang],
            reply_markup=KEYBOARDS["main_menu"][lang]
        )
        return

    # Ваш поиск (например, FTS5 или LIKE)
    results = search_in_all_tables(text)
    if not results:
        await state.clear()
        await message.answer(
            {"kk": "Нәтиже табылмады.", "ru": "Ничего не найдено."}[lang],
            reply_markup=KEYBOARDS["main_menu"][lang]
        )
        return

    # Показываем inline-кнопки с результатами
    await state.update_data(results=results)
    header = {"kk": "Табылған нәтижелер:", "ru": "Найдены результаты:"}[lang]
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=r["button_name"], callback_data=f"search:{i}")]
            for i, r in enumerate(results)
        ]
    )
    await message.answer(header, reply_markup=ReplyKeyboardRemove())
    await message.answer(
        {"kk": "Нәтижені таңдаңыз:", "ru": "Выберите результат:"}[lang],
        reply_markup=kb
    )
    await state.set_state(UserStates.choosing_result)


# ——— ХЭНДЛЕР ВЫБОРА РЕЗУЛЬТАТА ———
@dp.callback_query(lambda c: c.data and c.data.startswith("search:"))
async def process_search_callback(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = data["language"]
    results = data.get("results", [])
    idx = int(callback.data.split(":", 1)[1])

    if 0 <= idx < len(results):
        r = results[idx]
        # Отправляем текст в Markdown
        await callback.message.answer(
            f"*{r['button_name']}*\n\n{r['text_info']}",
            parse_mode="Markdown"
        )
        if r.get("file_path"):
            await callback.message.answer_document(types.FSInputFile(r["file_path"]))

    # Сбрасываем и возвращаем главное меню
    await callback.answer()
    await callback.message.answer(
        get_message("choose_section", lang),
        reply_markup=KEYBOARDS["main_menu"][lang]
    )
    await state.clear()

# Список кнопок подменю бакалавриата
BACHELOR_BUTTONS = [
    "📚 Мемлекеттік білім беру тапсырысы", 
    "📚 Государственный образовательный заказ",
    "📝 ҰБТ",
    "📝 ЕНТ",
    "📅 Талапкердің күнтізбесі",
    "📅 Календарь абитуриента",
    "📄 Қажетті құжаттар",
    "📄 Необходимые документы",
    "🎓 Білім бағдарламалары",
    "🎓 Образовательные программы",
    "📖 Бейіндік пәндері",
    "📖 Профильные предметы",
    "🧑‍🏫 'Педагогика ғылымдары' арнайы емтиханы",
    "🧑‍🏫 Спецэкзамен 'Педагогические науки'",
    "🎭 Шығармашылық ББ",
    "🎭 Творческие ОП",
    "💰 Оқу ақысы", 
    "💰 Стоимость обучения",
    "📜 Қабылдау ережелері",
    "📜 Правила приема"    
]

MASTER_BUTTONS = [
    "Мемлекеттік білім беру тапсырысы маг", 
    "Государственный образовательный заказ маг",
    "ББ",
    "ОП",
    "Қажетті құжаттар маг",
    "Необходимые документы маг",
    "Байланыс",
    "Контакты"
]

DOCTORAL_BUTTONS = [
    "Докторантура Мемлекеттік білім беру тапсырысы", 
    "Докторантура Государственный образовательный заказ",
    "Докторантура Білім бағдарламалары",
    "Докторантура Образовательные программы",
    "Докторантура Қажетті құжаттар",
    "Докторантура Необходимые документы",
    "Докторантура Байланыс",
    "Докторантура Контакты",
    "Докторантура Түсу емтихандарының бағдарламалары",
    "Докторантура Программы вступительных экзаменов"
]


# Добавьте обработчик для кнопок подменю Магистратуры
@dp.message(lambda msg: msg.text in MASTER_BUTTONS)
async def handle_master_info(message: types.Message, state: FSMContext) -> None:
    """Обработка кнопок подменю магистратуры"""
    current_state = await state.get_state()
    if current_state == UserStates.master_menu.state:
        await send_info(message, state, "master_info")


# Обработчик информации бакалавриата
@dp.message(lambda msg: msg.text in BACHELOR_BUTTONS)
async def handle_bachelor_info(message: types.Message, state: FSMContext) -> None:
    """Обработка кнопок подменю бакалавриата"""
    current_state = await state.get_state()
    if current_state == UserStates.bachelor_menu.state:
        await send_info(message, state, "bachelor_info")
    # elif current_state == UserStates.magister_menu.state:
    #     await send_info(message, state, "magister_info")

# Обработчик для кнопок подменю Докторантуры
@dp.message(lambda msg: msg.text in DOCTORAL_BUTTONS)
async def handle_doctoral_info(message: types.Message, state: FSMContext) -> None:
    """Обработка кнопок подменю докторантуры"""
    current_state = await state.get_state()
    if current_state == UserStates.doctoral_menu.state:
        await send_info(message, state, "doctoral_info")



# Обработчик смены языка
@dp.message(F.text.in_(["🌍 Тілді өзгерту", "🌍 Сменить язык"]))
async def change_language(message: types.Message, state: FSMContext) -> None:
    """Обработка запроса на смену языка"""
    await message.answer(
        f"{get_message('welcome', 'kk')} / {get_message('welcome', 'ru')}", 
        reply_markup=get_language_keyboard()
    )
    await state.set_state(UserStates.choose_language)
     # ✅ Проверяем, что язык обнуляется при смене
    data = await state.get_data()
    print(f"DEBUG: После смены языка state: {data}")



# Обновите обработчики кнопки "Назад", чтобы они поддерживали состояние меню Магистратуры
@dp.message(F.text == "🔙 Назад")
async def go_back(message: types.Message, state: FSMContext) -> None:
    """Обработка нажатия кнопки 'Назад'"""
    data = await state.get_data()
    previous_state = data.get("previous_state", UserStates.main_menu.state)
    language = data.get("language", "ru")
    
    # Определение, какую клавиатуру показать в зависимости от предыдущего состояния
    if previous_state == UserStates.main_menu.state:
        keyboard_type = "main_menu"
        target_state = UserStates.main_menu
    elif previous_state == UserStates.bachelor_menu.state:
        keyboard_type = "bachelor_menu"
        target_state = UserStates.bachelor_menu
    elif previous_state == UserStates.master_menu.state:
        keyboard_type = "master_menu"
        target_state = UserStates.master_menu
    elif previous_state == UserStates.doctoral_menu.state:
        keyboard_type = "doctoral_menu"
        target_state = UserStates.doctoral_menu
    else:
        keyboard_type = "main_menu"
        target_state = UserStates.main_menu
    
    await message.answer(
        get_message("back", language), 
        reply_markup=KEYBOARDS[keyboard_type][language]
    )
    await state.set_state(target_state)

# То же самое обновление для казахской версии кнопки Назад
@dp.message(F.text=="🔙 Артқа")
async def go_back_kz(message: types.Message, state: FSMContext) -> None:
    """Обработка нажатия кнопки 'Назад'"""
    data = await state.get_data()
    previous_state = data.get("previous_state", UserStates.main_menu.state)
    language = data.get("language", "ru")
    
    # Определение, какую клавиатуру показать в зависимости от предыдущего состояния
    if previous_state == UserStates.main_menu.state:
        keyboard_type = "main_menu"
        target_state = UserStates.main_menu
    elif previous_state == UserStates.bachelor_menu.state:
        keyboard_type = "bachelor_menu"
        target_state = UserStates.bachelor_menu
    elif previous_state == UserStates.master_menu.state:
        keyboard_type = "master_menu"
        target_state = UserStates.master_menu
    elif previous_state == UserStates.doctoral_menu.state:
        keyboard_type = "doctoral_menu"
        target_state = UserStates.doctoral_menu
    else:
        keyboard_type = "main_menu"
        target_state = UserStates.main_menu
    
    await message.answer(
        get_message("back", language), 
        reply_markup=KEYBOARDS[keyboard_type][language]
    )
    await state.set_state(target_state)



# Обработчик кнопки "Как добраться" / "Қалай жетемін"
@dp.message(F.text.in_(["🗺️ Қалай жетемін", "🗺️ Как добраться"]))
async def handle_location(message: types.Message, state: FSMContext):
    """Отправка информации о местоположении университета с ссылками на карты"""
    data = await state.get_data()
    language = data.get("language", "ru")
    
    # Координаты университета (замените на реальные координаты)
    latitude = 50.290679  # Пример координат (замените на актуальные)
    longitude = 57.151828  # Пример координат (замените на актуальные)
    
    # Ссылки на карты
    google_maps_link = f"https://www.google.com/maps?q={latitude},{longitude}"
    dgis_link = "https://2gis.kz/aktobe/firm/70000001031721747/57.15221%2C50.290333?m=57.151828%2C50.290679%2F17.63"
    
    # Локализованные тексты
    texts = {
        "kk": {
            "location": "Университет мекенжайы:",
            "address": "​Ағайынды Жұбановтар көшесі 263, Ақтөбе",  # Замените на реальный адрес
            "maps": "Картадан қараңыз:",
            "google": "Google Maps",
            "dgis": "2ГИС"
        },
        "ru": {
            "location": "Адрес университета:",
            "address": "​Ағайынды Жұбановтар көшесі 263, Ақтөбе",  # Замените на реальный адрес
            "maps": "Посмотреть на карте:",
            "google": "Google Maps",
            "dgis": "2ГИС"
        }
    }
    
    text = texts[language]
    
    # Создаем инлайн клавиатуру с кнопками-ссылками
    keyboard = types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(text=text["google"], url=google_maps_link),
                types.InlineKeyboardButton(text=text["dgis"], url=dgis_link)
            ]
        ]
    )
    
    # Отправляем сообщение с локацией и кнопками
    await message.answer(
        f"{text['location']}\n{text['address']}\n\n{text['maps']}",
        reply_markup=keyboard
    )
    
    # Также можно отправить локацию как отдельное сообщение
    await message.answer_location(latitude=latitude, longitude=longitude)

# Список ваших Telegram user_id, которые имеют право просматривать обратную связь
ADMIN_IDS = {940771019}  # <-- подставьте сюда свои id


@dp.message(Command("view_feedback"))
async def cmd_view_feedback(message: types.Message):
    # Проверяем, что запрос пришёл от админа
    if message.from_user.id not in ADMIN_IDS:
        return  # просто игнорируем остальных

    # Берём последние 20 отзывов из БД
    feedbacks = get_recent_feedbacks(limit=20)
    if not feedbacks:
        await message.answer("Нет сохранённых отзывов.")
        return

    # Формируем текст сообщения
    chunks = []
    text = ""
    for fb in feedbacks:
        # fb = (id, username, message, language, timestamp)
        fid, username, msg, lang, ts = fb
        line = f"{fid}. @{username or '—'} ({lang}, {ts.strftime('%Y-%m-%d %H:%M')}):\n{msg}\n\n"
        # разбиваем по 3000 символов, чтобы не попасть в лимит Telegram
        if len(text) + len(line) > 3000:
            chunks.append(text)
            text = ""
        text += line
    chunks.append(text)

    # Шлём частями
    for chunk in chunks:
        await message.answer(chunk)

@dp.message(Command("whoami"))
async def cmd_whoami(message: types.Message):
    await message.answer(f"Ваш user_id: `{message.from_user.id}`", parse_mode="Markdown")



# Основная функция запуска бота
async def main() -> None:
    """Точка входа для запуска бота"""
    logger.info("Запуск бота...")
    try:
        await dp.start_polling(bot)
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}")
    finally:
        await bot.session.close()

if __name__ == '__main__':
    asyncio.run(main())
