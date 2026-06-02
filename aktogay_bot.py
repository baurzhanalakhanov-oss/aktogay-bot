"""
Telegram-бот: Ассистент ЭС и КИПиА — KAZ Minerals Актогай
Установка: pip install python-telegram-bot anthropic
Запуск:    python aktogay_bot.py
"""

import logging
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    ContextTypes, filters, ConversationHandler
)
import anthropic

# ───────────────────────────────────────────────
# НАСТРОЙКИ — замени на свои ключи
# ───────────────────────────────────────────────
TELEGRAM_TOKEN  = ""
ANTHROPIC_KEY   = ""

# ───────────────────────────────────────────────
# Контекст предприятия (добавляется ко всем запросам)
# ───────────────────────────────────────────────
ENTERPRISE_CONTEXT = """
Предприятие: KAZ Minerals Актогай — крупный медный горно-обогатительный комбинат (ГОК) в Казахстане.
Включает: открытый карьер, обогатительную фабрику (флотация, SAG-мельницы, шаровые мельницы).
Питание: высоковольтная сеть 110/35/10/6 кВ.
Оборудование: ABB, Siemens, Rockwell Automation (Allen-Bradley), DCS/АСУ ТП.
Нормативная база: казахстанские ПУЭ, ПТЭЭП, Правила ОТ, стандарты KAZ Minerals (HSE).
Пользователь — начальник службы электриков и КИПиА.
"""

# ───────────────────────────────────────────────
# Системные промпты для каждого режима
# ───────────────────────────────────────────────
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

logging.basicConfig(
    format="%(asctime)s — %(levelname)s — %(message)s",
    level=logging.INFO
)

client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)

# ───────────────────────────────────────────────
# Главное меню
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
# Handlers
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

    # Ограничиваем историю последними 10 сообщениями
    if len(history) > 10:
        history = history[-10:]
        context.user_data["history"] = history

    await update.message.chat.send_action("typing")

    try:
        response = client.messages.create(
            model      = "claude-sonnet-4-20250514",
            max_tokens = 1000,
            system     = MODES[mode]["system"],
            messages   = history
        )
        answer = response.content[0].text
        history.append({"role": "assistant", "content": answer})

        # Telegram ограничивает сообщения до 4096 символов
        if len(answer) > 4000:
            for i in range(0, len(answer), 4000):
                await update.message.reply_text(answer[i:i+4000])
        else:
            await update.message.reply_text(answer)

    except Exception as e:
        logging.error(f"Ошибка API: {e}")
        await update.message.reply_text(
            "⚠️ Ошибка при обращении к ИИ. Попробуй ещё раз."
        )

    return CHATTING


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 *Как пользоваться ботом:*\n\n"
        "1. Выбери раздел из меню\n"
        "2. Задай вопрос текстом\n"
        "3. Бот запомнит контекст диалога (последние 10 сообщений)\n"
        "4. Нажми «Главное меню» чтобы сменить раздел\n\n"
        "❓ /start — перезапустить бота",
        parse_mode="Markdown"
    )

# ───────────────────────────────────────────────
# Запуск
# ───────────────────────────────────────────────
def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            CHOOSING_MODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, choose_mode)],
            CHATTING:      [MessageHandler(filters.TEXT & ~filters.COMMAND, chat)],
        },
        fallbacks=[CommandHandler("start", start), CommandHandler("help", help_cmd)],
    )

    app.add_handler(conv)
    app.add_handler(CommandHandler("help", help_cmd))

    logging.info("Бот запущен...")
    app.run_polling()

if __name__ == "__main__":
    main()
