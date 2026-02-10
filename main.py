import requests
import re
import random
import asyncio
import time
import logging
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.constants import ChatAction, ParseMode
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

# ==========================================
# إعدادات البوت والتوكن
# ==========================================
BOT_TOKEN = "8321203989:AAFCZTJx4mYM6DPSy9kQGixSy7XC22ZxmWk"
ADMIN_USERNAME = "t5lnn"  # معرف المدير للتحكم في البوت

# إعدادات السجلات (Logging) لرؤية الأخطاء بوضوح
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ==========================================
# متغيرات النظام (Global State)
# ==========================================
CHAT_HISTORY = {}
USER_STATE = {}
USER_CONTEXT = {} 

# إعدادات المزود (Provider Settings)
CURRENT_PROVIDER = "gemma" # القيم المتاحة: 'gemma' أو 'google'
GOOGLE_API_KEYS = [] 
GOOGLE_MODEL_NAME = "gemini-2.5-flash" 

# إحصائيات
BOT_STATS = {
    "total_users": set(),
    "messages_count": 0
}

# ==========================================
# النصوص التوجيهية (Prompts)
# ==========================================

RPG_SYSTEM_PROMPT = """
أنت "ZEUS AI"، راوي قصص تفاعلية (Dungeon Master) متطور جداً.
قواعدك الصارمة:
1. أنت لست مجرد بوت، أنت محرك قصصي.
2. مهمتك: سرد أحداث مشوقة جداً ووضع اللاعب في مواقف تتطلب الاختيار.
3. التنسيق مطلوب: استخدم الخط العريض للعناوين أو الأشياء المهمة بوضع نجمتين حول الكلمة (مثال: **المهمة**).
4. في نهاية كل رد، يجب أن تعطي اللاعب خيارات مرقمة واضحة (1. كذا، 2. كذا..).
5. لا تتخذ القرارات عن اللاعب، توقف وانتظر رده.
6. إذا اختار اللاعب رقماً، افهم سياق الرقم من رسالتك السابقة وأكمل القصة.
7. لا تستخدم الرموز الغريبة مثل الشرطات المائلة (\\) في الأسماء.
8. نوع القصة المحدد هو: {genre}.
9. طريقة بداية اللاعب هي: {start_type}. ابدأ القصة بناءً على هذا الإعداد فوراً.
"""

CHAT_SYSTEM_PROMPT = """
أنت "ZEUS AI"، مساعد ذكي ومتطور.
1. تحدث مع المستخدم بشكل طبيعي ومفيد.
2. أجب عن جميع الأسئلة بدقة.
3. كن ودوداً ومهذباً.
4. استخدم التنسيق (Bold, List) لجعل الإجابة مقروءة.
"""

# ==========================================
# دوال المساعدة والاتصال (Backend Logic)
# ==========================================

def clean_markdown(text):
    text = text.replace('\\', '')
    text = text.replace('**', '*')
    return text

# --- دالة الاتصال بـ Gemma ---
def ask_gemma(messages_list, retries=3):
    url = "https://gemma3.cc/api/chat"
    headers = {
        "User-Agent": random.choice([
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.1.1 Safari/605.1.15"
        ]),
        "Content-Type": "application/json",
        "Referer": "https://gemma3.cc/",
        "Origin": "https://gemma3.cc"
    }
    
    clean_messages = []
    for msg in messages_list:
        clean_messages.append({"role": msg["role"], "content": msg["content"]})

    payload = {
        "model": "gemma-3-27b",
        "messages": clean_messages
    }

    for attempt in range(retries):
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=30)
            if response.status_code == 200:
                raw_text = "".join(re.findall(r'\d+:"([^"]*)"', response.text))
                cleaned_text = raw_text.replace('\\n', '\n').replace('\\"', '"').strip()
                return clean_markdown(cleaned_text) if cleaned_text else "⚠️ رد فارغ من Gemma."
        except Exception as e:
            logger.error(f"Gemma Error {attempt+1}: {e}")
            time.sleep(2)
    return "❌ خادم Gemma مشغول حالياً."

# --- دالة الاتصال بـ Google Gemini ---
def ask_google(messages_list, retries=3):
    if not GOOGLE_API_KEYS:
        return "⚠️ لم يتم إضافة مفاتيح Google API بعد من قبل الأدمن."
    
    api_key = random.choice(GOOGLE_API_KEYS)
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GOOGLE_MODEL_NAME}:generateContent?key={api_key}"
    
    headers = {"Content-Type": "application/json"}
    
    contents = []
    for i, msg in enumerate(messages_list):
        role = "user" if msg["role"] == "user" else "model"
        contents.append({
            "role": role,
            "parts": [{"text": msg["content"]}]
        })

    payload = {
        "contents": contents,
        "generationConfig": {
            "temperature": 0.9,
            "maxOutputTokens": 2048
        }
    }

    for attempt in range(retries):
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=30)
            if response.status_code == 200:
                data = response.json()
                try:
                    text = data["candidates"][0]["content"]["parts"][0]["text"]
                    return clean_markdown(text)
                except KeyError:
                    return "⚠️ خطأ في قراءة رد Google."
            else:
                return f"❌ خطأ من Google: {response.status_code}"
        except Exception as e:
            logger.error(f"Google Error {attempt+1}: {e}")
            time.sleep(2)
    return "❌ تعذر الاتصال بخوادم Google."

# --- الموجه الذكي ---
def ask_ai_unified(messages_list):
    if CURRENT_PROVIDER == "google":
        return ask_google(messages_list)
    else:
        return ask_gemma(messages_list)

# --- أدوات الواجهة ---
def create_numeric_keyboard(text):
    options_indices = re.findall(r'(\d+)\.', text)
    buttons = []
    if options_indices:
        unique_options = sorted(list(set(options_indices)), key=int)
        row = []
        for opt in unique_options:
            row.append(KeyboardButton(opt))
            if len(row) == 3:
                buttons.append(row)
                row = []
        if row:
            buttons.append(row)
    
    buttons.append([KeyboardButton("🏠 القائمة الرئيسية")])
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)

async def send_smart_message(update, text, reply_markup=None):
    max_length = 4000
    if len(text) <= max_length:
        try:
            await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)
        except:
            await update.message.reply_text(text, reply_markup=reply_markup)
    else:
        parts = [text[i:i+max_length] for i in range(0, len(text), max_length)]
        for i, part in enumerate(parts):
            markup = reply_markup if i == len(parts) - 1 else None
            try:
                await update.message.reply_text(part, parse_mode=ParseMode.MARKDOWN, reply_markup=markup)
            except:
                await update.message.reply_text(part, reply_markup=markup)

# ==========================================
# قوائم وأزرار التنقل
# ==========================================

async def show_main_menu(update: Update):
    welcome_text = (
        "⚡ **أهلاً بك في ZEUS AI** ⚡\n\n"
        "أنا مساعدك الذكي وراوي قصصك المفضل.\n"
        f"💎 **المزود الحالي:** {CURRENT_PROVIDER.upper()}\n"
        "👇 **ماذا تريد أن تفعل اليوم؟**"
    )
    keyboard = [
        [KeyboardButton("⚔️ وضع RPG (لعبة)")],
        [KeyboardButton("💬 وضع الدردشة (Chat)")],
        [KeyboardButton("ℹ️ التعليمات"), KeyboardButton("👤 حسابي")]
    ]
    if update.effective_user.username == ADMIN_USERNAME:
        keyboard.append([KeyboardButton("⚙️ لوحة التحكم (Admin)")])

    markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text(clean_markdown(welcome_text), parse_mode=ParseMode.MARKDOWN, reply_markup=markup)

async def show_rpg_genres(update: Update):
    text = "🌍 **اختر العالم الذي تريد المغامرة فيه:**"
    keyboard = [
        [KeyboardButton("🐉 شيانشيا (Xianxia)"), KeyboardButton("👊 ووشيا (Wuxia)")],
        [KeyboardButton("🧟 رعب (Apocalypse)"), KeyboardButton("🚀 خيال علمي (Sci-Fi)")],
        [KeyboardButton("🏰 عصور وسطى (Fantasy)"), KeyboardButton("🌃 سايبر بانك (Cyberpunk)")],
        [KeyboardButton("🏠 القائمة الرئيسية")]
    ]
    markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=markup)

async def show_start_types(update: Update):
    text = "✨ **كيف تريد أن تكون بدايتك في هذا العالم؟**"
    keyboard = [
        [KeyboardButton("🖥️ امتلاك نظام (System Cheat)"), KeyboardButton("🥄 ملعقة ذهبية (نبيل/غني)")],
        [KeyboardButton("✨ هالة بطل (Protagonist Halo)"), KeyboardButton("👤 شخصية إضافية (Mob/Extra)")],
        [KeyboardButton("🎲 بداية عشوائية (Random)"), KeyboardButton("🔙 رجوع")]
    ]
    markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=markup)

# ==========================================
# لوحة تحكم الأدمن
# ==========================================

async def show_admin_panel(update: Update):
    if update.effective_user.username != ADMIN_USERNAME:
        return
    
    status_text = (
        "⚙️ **لوحة تحكم المدير (Zeus Control)**\n\n"
        f"📊 عدد المستخدمين: {len(BOT_STATS['total_users'])}\n"
        f"📡 المزود الحالي: **{CURRENT_PROVIDER}**\n"
        f"🔑 عدد مفاتيح Google: {len(GOOGLE_API_KEYS)}\n"
        f"🤖 نموذج جوجل: {GOOGLE_MODEL_NAME}"
    )
    keyboard = [
        [KeyboardButton("➕ إضافة مفتاح Google"), KeyboardButton("🔄 تبديل المزود")],
        [KeyboardButton("🗑️ حذف جميع المفاتيح"), KeyboardButton("🏠 القائمة الرئيسية")]
    ]
    markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text(clean_markdown(status_text), parse_mode=ParseMode.MARKDOWN, reply_markup=markup)

# ==========================================
# معالجة الأخطاء (هام جداً)
# ==========================================
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log the error and send a telegram message to notify the developer."""
    logger.error(msg="Exception while handling an update:", exc_info=context.error)
    # لا نرسل رسالة للمستخدم دائماً لتجنب الإزعاج، لكن نسجلها في الكونسول

# ==========================================
# معالجة النصوص والمنطق
# ==========================================

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    username = update.effective_user.username
    text = update.message.text
    
    BOT_STATS['total_users'].add(chat_id)
    BOT_STATS['messages_count'] += 1

    # القائمة الرئيسية
    if text == "🏠 القائمة الرئيسية":
        CHAT_HISTORY[chat_id] = []
        USER_STATE[chat_id] = "MENU"
        await show_main_menu(update)
        return

    # الأدمن
    if text == "⚙️ لوحة التحكم (Admin)" and username == ADMIN_USERNAME:
        USER_STATE[chat_id] = "ADMIN_PANEL"
        await show_admin_panel(update)
        return

    # منطق لوحة التحكم
    if USER_STATE.get(chat_id) == "ADMIN_PANEL":
        if text == "🔄 تبديل المزود":
            global CURRENT_PROVIDER
            CURRENT_PROVIDER = "google" if CURRENT_PROVIDER == "gemma" else "gemma"
            await update.message.reply_text(f"✅ تم تغيير المزود إلى: **{CURRENT_PROVIDER}**", parse_mode=ParseMode.MARKDOWN)
            await show_admin_panel(update)
            return
        
        elif text == "➕ إضافة مفتاح Google":
            USER_STATE[chat_id] = "ADMIN_WAITING_KEY"
            instructions = (
                "🔑 **إضافة مفتاح Google Gemini**\n\n"
                "أرسل المفتاح الآن في رسالة.\n\n"
                "📌 **كيف تحصل على المفتاح؟**\n"
                "1. اذهب إلى Google AI Studio.\n"
                "2. اضغط Get API Key.\n"
                "3. انسخ المفتاح وأرسله هنا.\n\n"
                "🔗 [اضغط هنا لفتح Google Studio](https://aistudio.google.com/app/apikey)\n"
                "🎥 أو ابحث في يوتيوب: 'How to get Gemini API Key'"
            )
            await update.message.reply_text(instructions, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)
            return

        elif text == "🗑️ حذف جميع المفاتيح":
            GOOGLE_API_KEYS.clear()
            await update.message.reply_text("🗑️ تم حذف جميع المفاتيح.", parse_mode=ParseMode.MARKDOWN)
            await show_admin_panel(update)
            return

    if USER_STATE.get(chat_id) == "ADMIN_WAITING_KEY":
        if username == ADMIN_USERNAME:
            if len(text) > 20:
                GOOGLE_API_KEYS.append(text.strip())
                await update.message.reply_text(f"✅ تم إضافة المفتاح بنجاح! العدد الحالي: {len(GOOGLE_API_KEYS)}")
                USER_STATE[chat_id] = "ADMIN_PANEL"
                await show_admin_panel(update)
            else:
                await update.message.reply_text("⚠️ المفتاح يبدو قصيراً جداً، تأكد منه.")
        return

    # اختيار الأوضاع
    if text == "⚔️ وضع RPG (لعبة)":
        USER_STATE[chat_id] = "RPG_SELECT_GENRE"
        await show_rpg_genres(update)
        return
    
    if text == "💬 وضع الدردشة (Chat)":
        USER_STATE[chat_id] = "CHAT_MODE"
        CHAT_HISTORY[chat_id] = [{"role": "user", "content": CHAT_SYSTEM_PROMPT}, {"role": "model", "content": "مرحباً! أنا ZEUS، كيف يمكنني مساعدتك اليوم؟"}]
        await update.message.reply_text("💬 **أنت الآن في وضع الدردشة الحرة.**\nتحدث معي بشكل طبيعي!", parse_mode=ParseMode.MARKDOWN)
        return

    # إعدادات RPG
    if USER_STATE.get(chat_id) == "RPG_SELECT_GENRE":
        genre_clean = re.sub(r'[^\w\s]', '', text).strip()
        USER_CONTEXT[chat_id] = {"genre": genre_clean}
        USER_STATE[chat_id] = "RPG_SELECT_START"
        await show_start_types(update)
        return

    if USER_STATE.get(chat_id) == "RPG_SELECT_START":
        if text == "🔙 رجوع":
            USER_STATE[chat_id] = "RPG_SELECT_GENRE"
            await show_rpg_genres(update)
            return

        start_type_clean = re.sub(r'[^\w\s]', '', text).strip()
        genre = USER_CONTEXT[chat_id].get("genre", "خيال")
        final_system_prompt = RPG_SYSTEM_PROMPT.format(genre=genre, start_type=start_type_clean)
        
        CHAT_HISTORY[chat_id] = [{"role": "user", "content": final_system_prompt}]
        USER_STATE[chat_id] = "RPG_GAME"
        
        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
        
        loop = asyncio.get_running_loop()
        bot_reply = await loop.run_in_executor(None, ask_ai_unified, CHAT_HISTORY[chat_id])
        
        CHAT_HISTORY[chat_id].append({"role": "model", "content": bot_reply})
        markup = create_numeric_keyboard(bot_reply)
        await send_smart_message(update, bot_reply, reply_markup=markup)
        return

    # التفاعل داخل اللعبة
    if USER_STATE.get(chat_id) == "RPG_GAME":
        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
        
        CHAT_HISTORY[chat_id].append({"role": "user", "content": text})
        
        if len(CHAT_HISTORY[chat_id]) > 14:
            sys_msg = CHAT_HISTORY[chat_id][0]
            recent = CHAT_HISTORY[chat_id][-10:]
            CHAT_HISTORY[chat_id] = [sys_msg] + recent

        loop = asyncio.get_running_loop()
        bot_reply = await loop.run_in_executor(None, ask_ai_unified, CHAT_HISTORY[chat_id])
        
        CHAT_HISTORY[chat_id].append({"role": "model", "content": bot_reply})
        markup = create_numeric_keyboard(bot_reply)
        await send_smart_message(update, bot_reply, reply_markup=markup)
        return

    # التفاعل داخل الدردشة
    if USER_STATE.get(chat_id) == "CHAT_MODE":
        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
        
        CHAT_HISTORY[chat_id].append({"role": "user", "content": text})
        
        if len(CHAT_HISTORY[chat_id]) > 12:
            sys_msg = CHAT_HISTORY[chat_id][0]
            recent = CHAT_HISTORY[chat_id][-8:]
            CHAT_HISTORY[chat_id] = [sys_msg] + recent

        loop = asyncio.get_running_loop()
        bot_reply = await loop.run_in_executor(None, ask_ai_unified, CHAT_HISTORY[chat_id])
        
        CHAT_HISTORY[chat_id].append({"role": "model", "content": bot_reply})
        await send_smart_message(update, bot_reply)
        return
        
    if text == "ℹ️ التعليمات":
        await update.message.reply_text("اختر وضعاً من القائمة لتبدأ. في وضع RPG استخدم الأرقام للاختيار.")
        return
        
    if text == "👤 حسابي":
        await update.message.reply_text(f"🆔 معرفك: `{chat_id}`\n👤 المستخدم: @{username}", parse_mode=ParseMode.MARKDOWN)
        return

    await update.message.reply_text("الرجاء استخدام الأزرار في القائمة.")

# ==========================================
# دالة البدء
# ==========================================
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    CHAT_HISTORY[chat_id] = []
    USER_STATE[chat_id] = "MENU"
    await show_main_menu(update)

# ==========================================
# التشغيل الرئيسي
# ==========================================
if __name__ == "__main__":
    print("🚀 ZEUS AI (V3.1 Stable) is Running...")
    
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("admin", show_admin_panel))
    
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # إضافة معالج الأخطاء
    app.add_error_handler(error_handler)

    app.run_polling()