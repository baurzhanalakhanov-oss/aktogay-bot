"""
Telegram-бот: Ассистент ЭС и КИПиА — KAZ Minerals Актогай
Установка: pip install python-telegram-bot anthropic pypdf
Запуск:    python aktogay_bot.py

НОВЫЕ ВОЗМОЖНОСТИ:
  - /upload   — загрузить PDF-документ в базу знаний
  - /train    — добавить вопрос-ответ (обучение)
  - /docs     — список загруженных документов
  - /cleardocs — очистить базу документов
"""

import logging
import io
import json
import os
from datetime import datetime
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    ContextTypes, filters, ConversationHandler
)
import anthropic
from pypdf import PdfReader

# ───────────────────────────────────────────────
# НАСТРОЙКИ — замени на свои ключи
# ───────────────────────────────────────────────
TELEGRAM_TOKEN = ""
ANTHROPIC_KEY  = ""

# ID администраторов (кто может загружать PDF и обучать бота)
# Оставь пустым [] чтобы разрешить всем, или укажи список Telegram user_id
ADMIN_IDS = []  # Пример: [123456789, 987654321]

# Файл для хранения базы знаний (сохраняется между перезапусками)
KNOWLEDGE_FILE = "knowledge_base.json"

# ───────────────────────────────────────────────
# Контекст предприятия
# ───────────────────────────────────────────────
ENTERPRISE_CONTEXT = """
Предприятие: KAZ Minerals Актогай — крупный медный горно-обогатительный комбинат (ГОК) в Казахстане.
Включает: открытый карьер, обогатительную фабрику (флотация, SAG-мельницы, шаровые мельницы).
Питание: высоковольтная сеть 110/35/10/6 кВ.
Оборудование: ABB, Siemens, Rockwell Automation (Allen-Bradley), DCS/АСУ ТП.
Нормативная база: казахстанские ПУЭ, ПТЭЭП, Правила ОТ, стандарты KAZ Minerals (HSE).
Пользователь — начальник службы электриков и КИПиА.
"""

MODES = {
    "⚡ Техническая база": {
        "system": ENTERPRISE_CONTEXT + "Ты — опытный инженер-электрик и специалист КИПиА на ГОКах. "
            "Отвечаешь на технические вопросы: ЧП ABB/Siemens для мельниц и насосов, трансформаторы, "
            "кабели в горных условиях, датчики (давление, уровень, вибрация), ПЛК Allen-Bradley, DCS. "
            "Отвечай профессионально и кратко на русском языке.",
        "hint": "Задай технический вопрос по электрике или КИП"
    },
    "📋 Наряд-допуск / ОТ": {
        "system": ENTERPRISE_CONTEXT + "Ты — эксперт по охране труда и электробезопасности на горнорудных предприятиях Казахстана. "
            "Помогаешь оформлять наряды-допуски, составлять инструктажи, соблюдать ПУЭ, ПТЭЭП, HSE KAZ Minerals. "
            "Учитывай специфику горнорудного производства. Отвечай чётко на русском языке.",
        "hint": "Задай вопрос по охране труда или оформлению документов"
    },
    "🔧 Диагностика": {
        "system": ENTERPRISE_CONTEXT + "Ты — эксперт по диагностике электрооборудования и КИП на ГОКах. "
            "Помогаешь выявлять причины отказов: приводы мельниц, ЧП, трансформаторы, датчики (пыль, влага, вибрация), "
            "кабели в карьере, ПЛК/DCS. Предлагай пошаговый алгоритм диагностики. Отвечай на русском языке.",
        "hint": "Опиши симптомы неисправности оборудования"
    },
    "👷 Персонал": {
        "system": ENTERPRISE_CONTEXT + "Ты — помощник по управлению персоналом электротехнической службы ГОКа. "
            "Помогаешь с вахтовыми графиками, аттестациями, инструктажами, должностными инструкциями, "
            "служебными записками по казахстанскому ТК. Отвечай структурированно на русском языке.",
        "hint": "Задай вопрос по персоналу или кадровым документам"
    },
    "📅 ППР / Планирование": {
        "system": ENTERPRISE_CONTEXT + "Ты — специалист по ТОиР электрооборудования на ГОКах. "
            "Помогаешь составлять планы ППР, готовить остановы оборудования, планировать ЗИП, "
            "вести реестры. Учитывай режим 24/7 и вахтовую специфику. Отвечай структурированно на русском языке.",
        "hint": "Задай вопрос по планированию ТО или ремонтов"
    },
    "📄 Документация": {
        "system": ENTERPRISE_CONTEXT + "Ты — помощник по подготовке технической документации для ЭС ГОКа в Казахстане. "
            "Составляешь акты осмотра, протоколы измерений, отчёты об инцидентах, ТЗ на ремонт, заявки на ЗИП. "
            "Соблюдай формат казахстанских стандартов. Отвечай на русском языке.",
        "hint": "Опиши какой документ нужно составить"
    },
}

CHOOSING_MODE = 1
CHATTING      = 2
TRAINING      = 3

logging.basicConfig(
    format="%(asctime)s — %(levelname)s — %(message)s",
    level=logging.INFO
)

client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)

# ───────────────────────────────────────────────
# База знаний (PDF-документы + Q&A пары)
# ───────────────────────────────────────────────

def load_knowledge() -> dict:
    """Загружает базу знаний из файла."""
    if os.path.exists(KNOWLEDGE_FILE):
        with open(KNOWLEDGE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"documents": [], "qa_pairs": []}

def save_knowledge(kb: dict):
    """Сохраняет базу знаний в файл."""
    with open(KNOWLEDGE_FILE, "w", encoding="utf-8") as f:
        json.dump(kb, f, ensure_ascii=False, indent=2)

knowledge_base = load_knowledge()

def build_knowledge_context() -> str:
    """Собирает весь контекст из базы знаний для подстановки в промпт."""
    parts = []

    if knowledge_base["qa_pairs"]:
        qa_text = "\n".join(
            f"Q: {item['question']}\nA: {item['answer']}"
            for item in knowledge_base["qa_pairs"]
        )
        parts.append(f"=== ОБУЧАЮЩИЕ ПАРЫ ВОПРОС-ОТВЕТ ===\n{qa_text}")

    if knowledge_base["documents"]:
        for doc in knowledge_base["documents"]:
            # Берём первые 3000 символов каждого документа чтобы не переполнить контекст
            snippet = doc["text"][:3000]
            if len(doc["text"]) > 3000:
                snippet += "\n...[текст обрезан]"
            parts.append(f"=== ДОКУМЕНТ: {doc['name']} (загружен {doc['date']}) ===\n{snippet}")

    if parts:
        return "\n\n".join(parts) + "\n\nИспользуй эти материалы при ответах, если они релевантны вопросу.\n\n"
    return ""

def is_admin(user_id: int) -> bool:
    """Проверяет, является ли пользователь администратором."""
    if not ADMIN_IDS:
        return True  # Если список пуст — разрешено всем
    return user_id in ADMIN_IDS

# ───────────────────────────────────────────────
# Клавиатуры
# ───────────────────────────────────────────────

def main_menu_keyboard():
    keys = [[KeyboardButton(mode)] for mode in MODES]
    return ReplyKeyboardMarkup(keys, resize_keyboard=True)

def back_keyboard():
    return ReplyKeyboardMarkup(
        [[KeyboardButton("🏠 Главное меню")]],
        resize_keyboard=True
    )

# ───────────────────────────────────────────────
# Handlers — основные
# ───────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "⚡ *Ассистент ЭС и КИПиА*\n"
        "_KAZ Minerals Актогай_\n\n"
        "Выбери раздел:",
        parse_mode="Markdown",
        reply_markup=main_menu_keyboard()
    )
    return CHOOSING_MODE


async def choose_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text

    if text in MODES:
        context.user_data["mode"]    = text
        context.user_data["history"] = []
        hint = MODES[text]["hint"]
        await update.message.reply_text(
            f"{text}\n\n💬 {hint}\n\n_(Отправь вопрос или нажми «Главное меню»)_",
            parse_mode="Markdown",
            reply_markup=back_keyboard()
        )
        return CHATTING

    await update.message.reply_text("Выбери раздел из меню:", reply_markup=main_menu_keyboard())
    return CHOOSING_MODE


async def chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text

    if text == "🏠 Главное меню":
        context.user_data.clear()
        await update.message.reply_text("Выбери раздел:", reply_markup=main_menu_keyboard())
        return CHOOSING_MODE

    mode = context.user_data.get("mode")
    if not mode:
        await update.message.reply_text("Выбери раздел:", reply_markup=main_menu_keyboard())
        return CHOOSING_MODE

    history = context.user_data.setdefault("history", [])
    history.append({"role": "user", "content": text})

    if len(history) > 10:
        history = history[-10:]
        context.user_data["history"] = history

    await update.message.chat.send_action("typing")

    # Добавляем контекст из базы знаний к системному промпту
    knowledge_ctx = build_knowledge_context()
    system_prompt = MODES[mode]["system"]
    if knowledge_ctx:
        system_prompt = knowledge_ctx + system_prompt

    try:
        response = client.messages.create(
            model      = "claude-sonnet-4-20250514",
            max_tokens = 1000,
            system     = system_prompt,
            messages   = history
        )
        answer = response.content[0].text
        history.append({"role": "assistant", "content": answer})

        if len(answer) > 4000:
            for i in range(0, len(answer), 4000):
                await update.message.reply_text(answer[i:i+4000])
        else:
            await update.message.reply_text(answer)

    except Exception as e:
        logging.error(f"Ошибка API: {e}")
        await update.message.reply_text("⚠️ Ошибка при обращении к ИИ. Попробуй ещё раз.")

    return CHATTING

# ───────────────────────────────────────────────
# Handlers — загрузка PDF
# ───────────────────────────────────────────────

async def upload_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /upload — инструкция по отправке PDF."""
    if not is_admin(update.message.from_user.id):
        await update.message.reply_text("⛔ У вас нет прав для загрузки документов.")
        return

    await update.message.reply_text(
        "📎 *Загрузка PDF-документа*\n\n"
        "Просто отправь PDF-файл в этот чат.\n"
        "Текст будет извлечён и добавлен в базу знаний бота.\n\n"
        "⚠️ Рекомендуется загружать документы с текстовым слоем (не сканы).\n"
        "Максимальный размер файла: 20 МБ.",
        parse_mode="Markdown"
    )


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает загрузку PDF-файла."""
    if not is_admin(update.message.from_user.id):
        await update.message.reply_text("⛔ У вас нет прав для загрузки документов.")
        return

    doc = update.message.document
    if not doc.mime_type == "application/pdf":
        await update.message.reply_text("⚠️ Пожалуйста, отправь файл в формате PDF.")
        return

    if doc.file_size > 20 * 1024 * 1024:
        await update.message.reply_text("⚠️ Файл слишком большой. Максимум 20 МБ.")
        return

    await update.message.reply_text(f"⏳ Обрабатываю файл *{doc.file_name}*...", parse_mode="Markdown")

    try:
        # Скачиваем файл
        file = await context.bot.get_file(doc.file_id)
        file_bytes = await file.download_as_bytearray()

        # Извлекаем текст из PDF
        pdf_stream = io.BytesIO(bytes(file_bytes))
        reader = PdfReader(pdf_stream)

        pages_text = []
        for i, page in enumerate(reader.pages):
            page_text = page.extract_text()
            if page_text and page_text.strip():
                pages_text.append(f"[Стр. {i+1}]\n{page_text.strip()}")

        if not pages_text:
            await update.message.reply_text(
                "⚠️ Не удалось извлечь текст из PDF.\n"
                "Возможно, это отсканированный документ без текстового слоя."
            )
            return

        full_text = "\n\n".join(pages_text)
        total_chars = len(full_text)

        # Сохраняем в базу знаний
        doc_entry = {
            "name": doc.file_name,
            "date": datetime.now().strftime("%d.%m.%Y %H:%M"),
            "pages": len(reader.pages),
            "chars": total_chars,
            "text": full_text
        }
        knowledge_base["documents"].append(doc_entry)
        save_knowledge(knowledge_base)

        await update.message.reply_text(
            f"✅ *Документ добавлен в базу знаний!*\n\n"
            f"📄 Файл: {doc.file_name}\n"
            f"📑 Страниц: {len(reader.pages)}\n"
            f"🔤 Символов извлечено: {total_chars:,}\n\n"
            f"Теперь бот будет использовать этот документ при ответах.",
            parse_mode="Markdown"
        )

    except Exception as e:
        logging.error(f"Ошибка при обработке PDF: {e}")
        await update.message.reply_text(f"❌ Ошибка при обработке файла: {str(e)}")


async def docs_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /docs — список загруженных документов."""
    if not knowledge_base["documents"] and not knowledge_base["qa_pairs"]:
        await update.message.reply_text(
            "📂 База знаний пуста.\n\n"
            "Используй /upload чтобы загрузить PDF\n"
            "или /train чтобы добавить ответы на вопросы."
        )
        return

    msg_parts = ["📚 *База знаний бота:*\n"]

    if knowledge_base["documents"]:
        msg_parts.append(f"*PDF-документы ({len(knowledge_base['documents'])} шт.):*")
        for i, doc in enumerate(knowledge_base["documents"], 1):
            msg_parts.append(
                f"{i}. {doc['name']}\n"
                f"   📅 {doc['date']} | 📑 {doc['pages']} стр. | 🔤 {doc['chars']:,} симв."
            )

    if knowledge_base["qa_pairs"]:
        msg_parts.append(f"\n*Обучающие пары Q&A ({len(knowledge_base['qa_pairs'])} шт.):*")
        for i, qa in enumerate(knowledge_base["qa_pairs"], 1):
            q_short = qa["question"][:60] + "..." if len(qa["question"]) > 60 else qa["question"]
            msg_parts.append(f"{i}. ❓ {q_short}")

    await update.message.reply_text("\n".join(msg_parts), parse_mode="Markdown")


async def cleardocs_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /cleardocs — очистить базу документов."""
    if not is_admin(update.message.from_user.id):
        await update.message.reply_text("⛔ У вас нет прав для этого действия.")
        return

    knowledge_base["documents"] = []
    knowledge_base["qa_pairs"]  = []
    save_knowledge(knowledge_base)
    await update.message.reply_text("🗑️ База знаний очищена.")

# ───────────────────────────────────────────────
# Handlers — обучение (Q&A)
# ───────────────────────────────────────────────

WAITING_QUESTION = "waiting_question"
WAITING_ANSWER   = "waiting_answer"


async def train_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /train — начать добавление пары вопрос-ответ."""
    if not is_admin(update.message.from_user.id):
        await update.message.reply_text("⛔ У вас нет прав для обучения бота.")
        return

    context.user_data["train_state"] = WAITING_QUESTION
    await update.message.reply_text(
        "🎓 *Режим обучения*\n\n"
        "Введи *вопрос*, на который бот должен знать ответ.\n\n"
        "Например: _Какое напряжение на вводных ячейках ГРП-6?_\n\n"
        "Напиши /canceltraining чтобы отменить.",
        parse_mode="Markdown"
    )
    return TRAINING


async def train_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает ввод вопроса и ответа при обучении."""
    text = update.message.text
    state = context.user_data.get("train_state")

    if text == "🏠 Главное меню":
        context.user_data.pop("train_state", None)
        context.user_data.pop("train_question", None)
        await update.message.reply_text("Выбери раздел:", reply_markup=main_menu_keyboard())
        return CHOOSING_MODE

    if state == WAITING_QUESTION:
        context.user_data["train_question"] = text
        context.user_data["train_state"]    = WAITING_ANSWER
        await update.message.reply_text(
            f"✅ Вопрос принят:\n_{text}_\n\n"
            f"Теперь введи *ответ* на этот вопрос:",
            parse_mode="Markdown"
        )
        return TRAINING

    elif state == WAITING_ANSWER:
        question = context.user_data.get("train_question", "")
        answer   = text

        knowledge_base["qa_pairs"].append({
            "question": question,
            "answer":   answer,
            "date":     datetime.now().strftime("%d.%m.%Y %H:%M")
        })
        save_knowledge(knowledge_base)

        context.user_data.pop("train_state",    None)
        context.user_data.pop("train_question", None)

        await update.message.reply_text(
            f"✅ *Пара Q&A добавлена в базу знаний!*\n\n"
            f"❓ *Вопрос:* {question}\n"
            f"💡 *Ответ:* {answer[:200]}{'...' if len(answer) > 200 else ''}\n\n"
            f"Всего пар в базе: {len(knowledge_base['qa_pairs'])}\n\n"
            f"Используй /train чтобы добавить ещё.",
            parse_mode="Markdown",
            reply_markup=back_keyboard()
        )
        return CHOOSING_MODE

    return TRAINING


async def canceltraining_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отмена режима обучения."""
    context.user_data.pop("train_state",    None)
    context.user_data.pop("train_question", None)
    await update.message.reply_text(
        "❌ Обучение отменено.",
        reply_markup=main_menu_keyboard()
    )
    return CHOOSING_MODE


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 *Как пользоваться ботом:*\n\n"
        "*Основные команды:*\n"
        "/start — перезапустить бота\n"
        "/help — эта справка\n\n"
        "*База знаний:*\n"
        "/upload — загрузить PDF-документ\n"
        "/train — добавить пару вопрос-ответ\n"
        "/docs — список загруженных материалов\n"
        "/cleardocs — очистить базу знаний\n\n"
        "*Как использовать:*\n"
        "1. Выбери раздел из меню\n"
        "2. Задай вопрос текстом\n"
        "3. Бот запомнит контекст диалога (последние 10 сообщений)\n"
        "4. Нажми «Главное меню» чтобы сменить раздел",
        parse_mode="Markdown"
    )

# ───────────────────────────────────────────────
# Запуск
# ───────────────────────────────────────────────

def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            CommandHandler("train", train_cmd),
        ],
        states={
            CHOOSING_MODE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, choose_mode),
                MessageHandler(filters.Document.PDF, handle_document),
            ],
            CHATTING: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, chat),
                MessageHandler(filters.Document.PDF, handle_document),
            ],
            TRAINING: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, train_handler),
                CommandHandler("canceltraining", canceltraining_cmd),
            ],
        },
        fallbacks=[
            CommandHandler("start",           start),
            CommandHandler("help",            help_cmd),
            CommandHandler("canceltraining",  canceltraining_cmd),
        ],
    )

    app.add_handler(conv)
    app.add_handler(CommandHandler("help",       help_cmd))
    app.add_handler(CommandHandler("upload",     upload_cmd))
    app.add_handler(CommandHandler("docs",       docs_cmd))
    app.add_handler(CommandHandler("cleardocs",  cleardocs_cmd))

    # Обработчик PDF вне диалога (просто отправить файл)
    app.add_handler(MessageHandler(filters.Document.PDF, handle_document))

    logging.info("Бот запущен...")
    logging.info(f"База знаний: {len(knowledge_base['documents'])} документов, {len(knowledge_base['qa_pairs'])} Q&A пар")
    app.run_polling()


if __name__ == "__main__":
    main()
