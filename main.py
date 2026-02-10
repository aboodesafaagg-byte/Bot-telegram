import requests
import re
import random
import asyncio
import time
import logging
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from telegram.constants import ChatAction, ParseMode
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

# ==========================================
# إعدادات البوت والتوكن
# ==========================================
BOT_TOKEN = "8292364018:AAEvovWMM0kUb7d_GpW-6JV-U34Xz0usJPQ"
ADMIN_USERNAME = "t5lnn"

# إعدادات السجلات (Logging)
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

# إعدادات المزود
CURRENT_PROVIDER = "gemma"  # القيم المتاحة: 'gemma' أو 'google'
GOOGLE_API_KEYS = []
GOOGLE_MODEL_NAME = "gemini-2.5-flash" # تحديث للموديل الأسرع والأكثر استقراراً

# إحصائيات
BOT_STATS = {
    "total_users": set(),
    "messages_count": 0,
    "start_time": time.time()
}

# ==========================================
# النصوص التوجيهية (Prompts)
# ==========================================

RPG_SYSTEM_PROMPT = """
أنت "ZEUS"، محرك قصصي عالمي (Dungeon Master) متطور.
القواعد:
1. السرد بأسلوب روائي مشوق (Immersion).
2. استخدم **العناوين العريضة** و *المائل* للتأثيرات.
3. في نهاية كل رد، قدم 3-4 خيارات مرقمة واضحة.
4. الخيار الأخير دائماً: "أفعال أخرى..." لترك الحرية للاعب.
5. نوع القصة: {genre}.
6. حالة البداية: {start_type}.
7. لا تتخذ قرارات نيابة عن اللاعب. انتظر اختياره.
"""

CHAT_SYSTEM_PROMPT = """
أنت "ZEUS"، مساعد ذكي تجاري عالمي.
المعايير:
1. الإجابة باحترافية، دقة، وإيجاز.
2. تنسيق الردود باستخدام (Bold, Lists, Code Blocks).
3. كن ودوداً ولكن عملياً.
4. هدفك مساعدة المستخدم بأقصى سرعة.
"""

# ==========================================
# دوال المساعدة والاتصال (Backend Logic)
# ==========================================

def clean_markdown(text):
    """تنظيف النص لتجنب أخطاء التنسيق في تيليجرام"""
    text = text.replace('\\', '')
    # تصحيح النجوم المزدوجة إذا كانت غير مغلقة (بسيط)
    if text.count('**') % 2 != 0:
        text = text.replace('**', '')
    return text

# --- دالة الاتصال بـ Gemma ---
def ask_gemma(messages_list, retries=3):
    url = "https://gemma3.cc/api/chat"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
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
            response = requests.post(url, json=payload, headers=headers, timeout=25)
            if response.status_code == 200:
                # محاولة استخراج النص بطرق متعددة
                try:
                    raw_text = "".join(re.findall(r'\d+:"([^"]*)"', response.text))
                    cleaned_text = raw_text.replace('\\n', '\n').replace('\\"', '"').strip()
                    if cleaned_text:
                        return clean_markdown(cleaned_text)
                except:
                    pass
                return "⚠️ حدث خطأ في معالجة رد Gemma، حاول مرة أخرى."
        except Exception as e:
            logger.error(f"Gemma Error: {e}")
            time.sleep(1)
    return "❌ الخادم مشغول حالياً، يرجى المحاولة لاحقاً أو تغيير المزود."

# --- دالة الاتصال بـ Google Gemini ---
def ask_google(messages_list, retries=3):
    if not GOOGLE_API_KEYS:
        return "⚠️ النظام يحتاج إلى مفاتيح API (يرجى مراجعة الإدارة)."
    
    # اختيار مفتاح عشوائي لتوزيع الحمل
    api_key = random.choice(GOOGLE_API_KEYS)
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GOOGLE_MODEL_NAME}:generateContent?key={api_key}"
    
    headers = {"Content-Type": "application/json"}
    
    contents = []
    for msg in messages_list:
        role = "user" if msg["role"] == "user" else "model"
        contents.append({
            "role": role,
            "parts": [{"text": msg["content"]}]
        })

    payload = {
        "contents": contents,
        "generationConfig": {
            "temperature": 0.8,
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
                except (KeyError, IndexError):
                    return "⚠️ استجابة غير مفهومة من Google."
            elif response.status_code == 429: # Too Many Requests
                api_key = random.choice(GOOGLE_API_KEYS) # تغيير المفتاح والمحاولة
                time.sleep(2)
                continue
            else:
                logger.error(f"Google Error Status: {response.status_code} - {response.text}")
        except Exception as e:
            logger.error(f"Google Connection Error: {e}")
            time.sleep(1)
            
    return "❌ تعذر الاتصال بخوادم Google بعد عدة محاولات."

# --- الموجه الذكي الموحد ---
def ask_ai_unified(messages_list):
    if CURRENT_PROVIDER == "google":
        return ask_google(messages_list)
    else:
        return ask_gemma(messages_list)

# --- أدوات الواجهة ---
def create_numeric_keyboard(text):
    """إنشاء لوحة مفاتيح ديناميكية بناءً على الخيارات في النص"""
    options_indices = re.findall(r'(\d+)\.', text)
    buttons = []
    
    # أزرار الأرقام
    if options_indices:
        unique_options = sorted(list(set(options_indices)), key=int)
        row = []
        for opt in unique_options:
            row.append(KeyboardButton(opt))
            if len(row) == 4: # جعلها 4 في الصف لتبدو أفضل
                buttons.append(row)
                row = []
        if row:
            buttons.append(row)
    
    # أزرار التحكم الثابتة
    buttons.append([KeyboardButton("📝 كتابة رد حر"), KeyboardButton("🔄 إعادة المحاولة")])
    buttons.append([KeyboardButton("🏠 القائمة الرئيسية")])
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)

async def send_smart_message(update, text, reply_markup=None):
    """إرسال الرسائل الطويلة مجزأة"""
    max_length = 4000
    if len(text) <= max_length:
        try:
            await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)
        except:
            await update.message.reply_text(text, reply_markup=reply_markup) # Fallback without markdown
    else:
        parts = [text[i:i+max_length] for i in range(0, len(text), max_length)]
        for i, part in enumerate(parts):
            markup = reply_markup if i == len(parts) - 1 else None
            try:
                await update.message.reply_text(part, parse_mode=ParseMode.MARKDOWN, reply_markup=markup)
            except:
                await update.message.reply_text(part, reply_markup=markup)

# ==========================================
# قوائم وأزرار التنقل (UI/UX)
# ==========================================

async def show_main_menu(update: Update):
    user = update.effective_user
    welcome_text = (
        f"👋 **أهلاً بك يا {user.first_name} في ZEUS AI**\n"
        "ــــــــــــــــــــــــــــــــــــــــــــــــــــــــــــ\n"
        "🚀 **منصتك الذكية المتكاملة:**\n"
        "• استمتع بألعاب RPG لا نهائية.\n"
        "• تحدث مع مساعد ذكي فائق القدرة.\n"
        "• تبديل سلس بين المزودات العالمية.\n\n"
        f"💎 **الحالة:** {'🟢 متصل' if CURRENT_PROVIDER else '🔴 غير متصل'}\n"
        "👇 **اختر وجهتك التالية:**"
    )
    
    keyboard = [
        [KeyboardButton("⚔️ وضع اللعب (RPG)"), KeyboardButton("💬 المساعد الذكي (Chat)")],
        [KeyboardButton("👤 حسابي وإحصائياتي"), KeyboardButton("ℹ️ حول البوت")],
    ]
    
    if user.username == ADMIN_USERNAME:
        keyboard.append([KeyboardButton("⚙️ لوحة الإدارة (Admin)")])

    markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text(clean_markdown(welcome_text), parse_mode=ParseMode.MARKDOWN, reply_markup=markup)

async def show_rpg_genres(update: Update):
    text = "🎭 **اختر عالم قصتك:**\nاستعد لرحلة خيالية يتم إنشاؤها خصيصاً لك."
    keyboard = [
        [KeyboardButton("🐉 أساطير شرقية (Xianxia)"), KeyboardButton("🧙‍♂️ فانتازيا (Fantasy)")],
        [KeyboardButton("🧟 نهاية العالم (Zombie)"), KeyboardButton("🚀 فضاء (Sci-Fi)")],
        [KeyboardButton("🕵️ غموض وجريمة"), KeyboardButton("🏯 ساموراي (Wuxia)")],
        [KeyboardButton("🎲 عشوائي"), KeyboardButton("🏠 القائمة الرئيسية")]
    ]
    markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=markup)

async def show_start_types(update: Update):
    text = "✨ **بداية القدر:**\nكيف تريد أن تدخل هذا العالم؟"
    keyboard = [
        [KeyboardButton("👑 ملك/زعيم"), KeyboardButton("🗑️ منبوذ/فقير")],
        [KeyboardButton("🤖 لدي نظام (System)"), KeyboardButton("🧠 عبقري استراتيجي")],
        [KeyboardButton("⚔️ محارب مخضرم"), KeyboardButton("🎲 اختيار القدر")],
        [KeyboardButton("🔙 رجوع للقائمة")]
    ]
    markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=markup)

async def show_chat_menu(update: Update):
    text = "💬 **وضع الدردشة الذكية**\nاسألني أي شيء، أطلب كود برمجي، أو نصائح عامة."
    keyboard = [
        [KeyboardButton("🧹 مسح الذاكرة (Chat Reset)")],
        [KeyboardButton("🏠 القائمة الرئيسية")]
    ]
    markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=markup)

# ==========================================
# لوحة تحكم الأدمن (المطورة)
# ==========================================

async def show_admin_panel(update: Update):
    if update.effective_user.username != ADMIN_USERNAME:
        return
    
    uptime = int(time.time() - BOT_STATS['start_time']) // 60
    
    status_text = (
        "🔐 **لوحة التحكم المركزية (Admin Dashboard)**\n"
        "ــــــــــــــــــــــــــــــــــــــــــــــــــــــــــــ\n"
        f"👥 المستخدمين النشطين: `{len(BOT_STATS['total_users'])}`\n"
        f"📨 إجمالي الرسائل: `{BOT_STATS['messages_count']}`\n"
        f"⏱️ وقت التشغيل: `{uptime} دقيقة`\n"
        f"📡 المزود الحالي: **{CURRENT_PROVIDER.upper()}**\n"
        f"🔑 مفاتيح Google المتاحة: `{len(GOOGLE_API_KEYS)}`\n"
        "ــــــــــــــــــــــــــــــــــــــــــــــــــــــــــــ"
    )
    
    keyboard = [
        [KeyboardButton("➕ إضافة مفاتيح (Bulk)"), KeyboardButton("🔄 تبديل المزود")],
        [KeyboardButton("🗑️ حذف المفاتيح"), KeyboardButton("🏠 خروج")]
    ]
    markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text(clean_markdown(status_text), parse_mode=ParseMode.MARKDOWN, reply_markup=markup)

# ==========================================
# معالجة الأحداث والمنطق الرئيسي
# ==========================================

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    username = update.effective_user.username
    text = update.message.text
    
    # تحديث الإحصائيات
    BOT_STATS['total_users'].add(chat_id)
    BOT_STATS['messages_count'] += 1

    # --- التنقل العام ---
    if text in ["🏠 القائمة الرئيسية", "🏠 خروج"]:
        CHAT_HISTORY[chat_id] = []
        USER_STATE[chat_id] = "MENU"
        await show_main_menu(update)
        return

    # --- أدوات الأدمن ---
    if text == "⚙️ لوحة الإدارة (Admin)" and username == ADMIN_USERNAME:
        USER_STATE[chat_id] = "ADMIN_PANEL"
        await show_admin_panel(update)
        return

    if USER_STATE.get(chat_id) == "ADMIN_PANEL":
        if text == "🔄 تبديل المزود":
            global CURRENT_PROVIDER
            CURRENT_PROVIDER = "google" if CURRENT_PROVIDER == "gemma" else "gemma"
            await update.message.reply_text(f"✅ تم التبديل إلى: **{CURRENT_PROVIDER.upper()}**", parse_mode=ParseMode.MARKDOWN)
            await show_admin_panel(update)
            return
        
        elif text == "➕ إضافة مفاتيح (Bulk)":
            USER_STATE[chat_id] = "ADMIN_WAITING_KEY"
            msg = (
                "📥 **وضع الإضافة المتعددة**\n\n"
                "أرسل قائمة المفاتيح الآن.\n"
                "⚠️ **التعليمات:** ضع كل مفتاح في سطر جديد.\n\n"
                "مثال:\n"
                "`AIzaSyD...`\n"
                "`AIzaSyF...`"
            )
            await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)
            return

        elif text == "🗑️ حذف المفاتيح":
            GOOGLE_API_KEYS.clear()
            await update.message.reply_text("🗑️ تم حذف قاعدة بيانات المفاتيح بالكامل.")
            await show_admin_panel(update)
            return

    # --- منطق إضافة المفاتيح المتعددة ---
    if USER_STATE.get(chat_id) == "ADMIN_WAITING_KEY" and username == ADMIN_USERNAME:
        # تقسيم النص إلى أسطر ومعالجة كل سطر
        raw_keys = text.splitlines()
        added_count = 0
        
        for key in raw_keys:
            clean_key = key.strip()
            # التحقق البسيط من طول المفتاح (مفاتيح جوجل عادة طويلة)
            if len(clean_key) > 20: 
                GOOGLE_API_KEYS.append(clean_key)
                added_count += 1
        
        if added_count > 0:
            await update.message.reply_text(
                f"✅ **تمت العملية بنجاح!**\n\n"
                f"📥 تم استيراد: `{added_count}` مفتاح.\n"
                f"📊 الإجمالي الآن: `{len(GOOGLE_API_KEYS)}` مفتاح.",
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            await update.message.reply_text("⚠️ لم يتم العثور على مفاتيح صالحة في النص المرسل.")
        
        USER_STATE[chat_id] = "ADMIN_PANEL"
        await show_admin_panel(update)
        return

    # --- اختيار الأوضاع ---
    if text == "⚔️ وضع اللعب (RPG)":
        USER_STATE[chat_id] = "RPG_SELECT_GENRE"
        await show_rpg_genres(update)
        return
    
    if text == "💬 المساعد الذكي (Chat)":
        USER_STATE[chat_id] = "CHAT_MODE"
        CHAT_HISTORY[chat_id] = [{"role": "user", "content": CHAT_SYSTEM_PROMPT}, {"role": "model", "content": "مرحباً! أنا جاهز للمساعدة."}]
        await show_chat_menu(update)
        return

    # --- منطق RPG ---
    if USER_STATE.get(chat_id) == "RPG_SELECT_GENRE":
        if text == "🏠 القائمة الرئيسية": 
            await show_main_menu(update); return
        
        genre = text.replace("🐉 ", "").replace("🧟 ", "").strip()
        USER_CONTEXT[chat_id] = {"genre": genre}
        USER_STATE[chat_id] = "RPG_SELECT_START"
        await show_start_types(update)
        return

    if USER_STATE.get(chat_id) == "RPG_SELECT_START":
        if text == "🔙 رجوع للقائمة":
            USER_STATE[chat_id] = "RPG_SELECT_GENRE"
            await show_rpg_genres(update)
            return

        start_type = text.strip()
        genre = USER_CONTEXT[chat_id].get("genre", "Fantasy")
        
        # تجهيز بداية القصة
        prompt = RPG_SYSTEM_PROMPT.format(genre=genre, start_type=start_type)
        CHAT_HISTORY[chat_id] = [{"role": "user", "content": prompt}]
        
        USER_STATE[chat_id] = "RPG_GAME"
        await process_ai_response(update, chat_id, text=None, is_rpg=True) # Start generation
        return

    if USER_STATE.get(chat_id) == "RPG_GAME":
        if text == "📝 كتابة رد حر":
            await update.message.reply_text("⌨️ اكتب ما تريد فعله بالتحديد:")
            return
        if text == "🔄 إعادة المحاولة":
            # إزالة آخر رد للبوت والمحاولة مجدداً
            if len(CHAT_HISTORY[chat_id]) > 1:
                if CHAT_HISTORY[chat_id][-1]["role"] == "model":
                    CHAT_HISTORY[chat_id].pop()
                await process_ai_response(update, chat_id, text=None, is_rpg=True)
            return

        await process_ai_response(update, chat_id, text, is_rpg=True)
        return

    # --- منطق الدردشة ---
    if USER_STATE.get(chat_id) == "CHAT_MODE":
        if text == "🧹 مسح الذاكرة (Chat Reset)":
            CHAT_HISTORY[chat_id] = [{"role": "user", "content": CHAT_SYSTEM_PROMPT}]
            await update.message.reply_text("🧹 **تم مسح ذاكرة المحادثة.** ابدأ من جديد.", parse_mode=ParseMode.MARKDOWN)
            return
        
        await process_ai_response(update, chat_id, text, is_rpg=False)
        return
        
    # --- معلومات المستخدم ---
    if text == "👤 حسابي وإحصائياتي":
        await update.message.reply_text(
            f"👤 **ملف المستخدم**\n"
            f"🆔 ID: `{chat_id}`\n"
            f"📛 الاسم: {update.effective_user.full_name}\n"
            f"🎭 الوضع الحالي: {USER_STATE.get(chat_id, 'None')}",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    if text == "ℹ️ حول البوت":
        await update.message.reply_text(
            "🤖 **ZEUS AI V4.0 (Commercial Edition)**\n\n"
            "بوت متطور يعتمد على تقنيات Google Gemini & Gemma.\n"
            "مخصص للألعاب التفاعلية والذكاء الاصطناعي التوليدي.\n"
            "تم التطوير والتحسين ليكون أسرع وأذكى."
        )
        return

    # رسالة افتراضية
    if USER_STATE.get(chat_id) == "MENU":
        await show_main_menu(update)

# ==========================================
# معالجة الردود (AI Processor)
# ==========================================
async def process_ai_response(update, chat_id, text, is_rpg):
    """دالة مركزية لمعالجة وإرسال ردود الذكاء الاصطناعي"""
    await context_action(update.effective_chat.id, context=None, action=ChatAction.TYPING) # Placeholder for action
    
    # إضافة رسالة المستخدم (إذا وجدت)
    if text:
        CHAT_HISTORY[chat_id].append({"role": "user", "content": text})
    
    # إدارة الذاكرة (Truncation)
    max_history = 16 if is_rpg else 10
    if len(CHAT_HISTORY[chat_id]) > max_history:
        system_msg = CHAT_HISTORY[chat_id][0]
        recent_msgs = CHAT_HISTORY[chat_id][-(max_history-1):]
        CHAT_HISTORY[chat_id] = [system_msg] + recent_msgs

    # إرسال مؤشر الكتابة
    await update.effective_chat.send_action(ChatAction.TYPING)

    # جلب الرد في خيط منفصل لتجنب تجميد البوت
    loop = asyncio.get_running_loop()
    bot_reply = await loop.run_in_executor(None, ask_ai_unified, CHAT_HISTORY[chat_id])
    
    # حفظ الرد
    CHAT_HISTORY[chat_id].append({"role": "model", "content": bot_reply})
    
    # تحديد نوع الأزرار
    markup = create_numeric_keyboard(bot_reply) if is_rpg else None
    if not is_rpg:
        # أزرار الدردشة البسيطة
        markup = ReplyKeyboardMarkup([[KeyboardButton("🧹 مسح الذاكرة (Chat Reset)"), KeyboardButton("🏠 القائمة الرئيسية")]], resize_keyboard=True)

    await send_smart_message(update, bot_reply, reply_markup=markup)

async def context_action(chat_id, context, action):
    """مساعد لإرسال الأكشن"""
    pass # يتم التعامل معه داخل process_ai_response مباشرة

# ==========================================
# دالة البدء
# ==========================================
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    CHAT_HISTORY[chat_id] = []
    USER_STATE[chat_id] = "MENU"
    await show_main_menu(update)

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error(msg="Exception while handling an update:", exc_info=context.error)

# ==========================================
# التشغيل الرئيسي
# ==========================================
if __name__ == "__main__":
    print("🚀 ZEUS AI (V4.0 Commercial) is Starting...")
    print(f"📡 Provider: {CURRENT_PROVIDER}")
    print(f"👮 Admin: {ADMIN_USERNAME}")

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("admin", show_admin_panel))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_error_handler(error_handler)

    print("✅ Bot is Online & Ready!")
    app.run_polling()