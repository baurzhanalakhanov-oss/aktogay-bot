"""
Telegram-бот: Ассистент ЭС и КИПиА — KAZ Minerals Актогай
Установка: pip install python-telegram-bot groq pypdf
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
from groq import Groq
from pypdf import PdfReader

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
GROQ_API_KEY   = os.getenv("GROQ_API_KEY", "")

ADMIN_IDS = []
KNOWLEDGE_FILE = "knowledge_base.json"

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
logging.getLogger("httpx").setLevel(logging.WARNING)

client = Groq(api_key=GROQ_API_KEY)

def load_knowledge() -> dict:
    if os.path.exists(KNOWLEDGE_FILE):
        with open(KNOWLEDGE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"documents": [], "qa_pairs": []}

def save_knowledge(kb: dict):
    with open(KNOWLEDGE_FILE, "w", encoding="utf-8") as f:
        json.dump(kb, f, ensure_ascii=False, indent=2)

knowledge_base = load_knowledge()

def build_knowledge_context() -> str:
    parts = []
    if knowledge_base["qa_pairs"]:
        qa_text = "\n".join(
            f"Q: {item['question']}\nA: {item['answer']}"
            for item in knowledge_base["qa_pairs"]
        )
        parts.append(f"=== ОБУЧАЮЩИЕ ПАРЫ ВОПРОС-ОТВЕТ ===\n{qa_text}")
    if knowledge_base["documents"]:
        for doc in knowledge_base["documents"]:
            snippet = doc["text"][:3000]
            if len(doc["text"]) > 3000:
                snippet += "\n...[текст обрезан]"
            parts.append(f"=== ДОКУМЕНТ: {doc['name']} ===\n{snippet}")
    if parts:
        return "\n\n".join(parts) + "\n\nИспользуй эти материалы при ответах, если они релевантны вопросу.\n\n"
    return ""

def is_admin(user_id: int) -> bool:
    if not ADMIN_IDS:
        return True
    return user_id in ADMIN_IDS

def main_menu_keyboard():
    keys = [[KeyboardButton(mode)] for mode in MODES]
    return ReplyKeyboardMarkup(keys, resize_keyboard=True)

def back_keyboard():
    return ReplyKeyboardMarkup([[KeyboardButton("🏠 Главное меню")]], resize_keyboard=True)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "⚡ *Ассистент ЭС и КИПиА*\n_KAZ Minerals Актогай_\n\nВыбери раздел:",
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

    knowledge_ctx = build_knowledge_context()
    system_prompt = MODES[mode]["system"]
    if knowledge_ctx:
        system_prompt = knowledge_ctx + system_prompt

    try:
        response = client.chat.completions.create(
            model    = "llama-3.3-70b-versatile",
            messages = [{"role": "system", "content": system_prompt}] + history,
            max_tokens = 1000,
        )
        answer = response.choices[0].message.content
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

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.message.from_user.id):
        await update.message.reply_text("⛔ У вас нет прав для загрузки документов.")
        return

    doc = update.message.document
    if doc.mime_type != "application/pdf":
        await update.message.reply_text("⚠️ Пожалуйста, отправь файл в формате PDF.")
        return

    if doc.file_size > 20 * 1024 * 1024:
        await update.message.reply_text("⚠️ Файл слишком большой. Максимум 20 МБ.")
        return

    await update.message.reply_text(f"⏳ Обрабатываю *{doc.file_name}*...", parse_mode="Markdown")

    try:
        file       = await context.bot.get_file(doc.file_id)
        file_bytes = await file.download_as_bytearray()
        reader     = PdfReader(io.BytesIO(bytes(file_bytes)))

        pages_text = []
        for i, page in enumerate(reader.pages):
            t = page.extract_text()
            if t and t.strip():
                pages_text.append(f"[Стр. {i+1}]\n{t.strip()}")

        if not pages_text:
            await update.message.reply_text(
                "⚠️ Не удалось извлечь текст из PDF.\n"
                "Возможно, это отсканированный документ без текстового слоя."
            )
            return

        full_text = "\n\n".join(pages_text)

        knowledge_base["documents"].append({
            "name":  doc.file_name,
            "date":  datetime.now().strftime("%d.%m.%Y %H:%M"),
            "pages": len(reader.pages),
            "chars": len(full_text),
            "text":  full_text
        })
        save_knowledge(knowledge_base)

        await update.message.reply_text(
            f"✅ *Документ добавлен в базу знаний!*\n\n"
            f"📄 {doc.file_name}\n"
            f"📑 Страниц: {len(reader.pages)}\n"
            f"🔤 Символов: {len(full_text):,}\n\n"
            f"Теперь бот будет использовать этот документ при ответах.",
            parse_mode="Markdown"
        )

    except Exception as e:
        logging.error(f"Ошибка PDF: {e}")
        await update.message.reply_text(f"❌ Ошибка при обработке файла: {str(e)}")

async def docs_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not knowledge_base["documents"] and not knowledge_base["qa_pairs"]:
        await update.message.reply_text(
            "📂 База знаний пуста.\n\nОтправь PDF-файл прямо в чат чтобы добавить документ.\n/train — добавить вопрос-ответ."
        )
        return
    parts = ["📚 *База знаний:*\n"]
    if knowledge_base["documents"]:
        parts.append(f"*PDF-документы ({len(knowledge_base['documents'])} шт.):*")
        for i, d in enumerate(knowledge_base["documents"], 1):
            parts.append(f"{i}. {d['name']}\n   📅 {d['date']} | 📑 {d['pages']} стр.")
    if knowledge_base["qa_pairs"]:
        parts.append(f"\n*Q&A пар: {len(knowledge_base['qa_pairs'])}*")
    await update.message.reply_text("\n".join(parts), parse_mode="Markdown")

async def cleardocs_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.message.from_user.id):
        await update.message.reply_text("⛔ Нет прав.")
        return
    knowledge_base["documents"] = []
    knowledge_base["qa_pairs"]  = []
    save_knowledge(knowledge_base)
    await update.message.reply_text("🗑️ База знаний очищена.")

WAITING_QUESTION = "waiting_question"
WAITING_ANSWER   = "waiting_answer"

async def train_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.message.from_user.id):
        await update.message.reply_text("⛔ Нет прав.")
        return
    context.user_data["train_state"] = WAITING_QUESTION
    await update.message.reply_text(
        "🎓 *Режим обучения*\n\nВведи *вопрос* на который бот должен знать ответ.\n\n/canceltraining — отменить.",
        parse_mode="Markdown"
    )
    return TRAINING

async def train_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text  = update.message.text
    state = context.user_data.get("train_state")

    if text == "🏠 Главное меню":
        context.user_data.pop("train_state",    None)
        context.user_data.pop("train_question", None)
        await update.message.reply_text("Выбери раздел:", reply_markup=main_menu_keyboard())
        return CHOOSING_MODE

    if state == WAITING_QUESTION:
        context.user_data["train_question"] = text
        context.user_data["train_state"]    = WAITING_ANSWER
        await update.message.reply_text(
            f"✅ Вопрос: _{text}_\n\nТеперь введи *ответ*:",
            parse_mode="Markdown"
        )
        return TRAINING

    elif state == WAITING_ANSWER:
        question = context.user_data.pop("train_question", "")
        context.user_data.pop("train_state", None)
        knowledge_base["qa_pairs"].append({
            "question": question,
            "answer":   text,
            "date":     datetime.now().strftime("%d.%m.%Y %H:%M")
        })
        save_knowledge(knowledge_base)
        await update.message.reply_text(
            f"✅ *Добавлено в базу знаний!*\n\n❓ {question}\n💡 {text[:200]}\n\nВсего Q&A: {len(knowledge_base['qa_pairs'])}",
            parse_mode="Markdown",
            reply_markup=back_keyboard()
        )
        return CHOOSING_MODE

    return TRAINING

async def canceltraining_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("train_state",    None)
    context.user_data.pop("train_question", None)
    await update.message.reply_text("❌ Отменено.", reply_markup=main_menu_keyboard())
    return CHOOSING_MODE

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 *Команды:*\n\n"
        "/start — главное меню\n"
        "/docs — список загруженных документов\n"
        "/train — добавить вопрос-ответ\n"
        "/cleardocs — очистить базу знаний\n\n"
        "📎 *Загрузка PDF:* просто отправь файл в чат",
        parse_mode="Markdown"
    )

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
            CommandHandler("start",          start),
            CommandHandler("help",           help_cmd),
            CommandHandler("canceltraining", canceltraining_cmd),
        ],
    )

    app.add_handler(conv)
    app.add_handler(CommandHandler("help",      help_cmd))
    app.add_handler(CommandHandler("docs",      docs_cmd))
    app.add_handler(CommandHandler("cleardocs", cleardocs_cmd))
    app.add_handler(MessageHandler(filters.Document.PDF, handle_document))

    logging.info("Бот запущен...")
    app.run_polling()

if __name__ == "__main__":
    main()
