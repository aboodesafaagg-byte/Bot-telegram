import requests
import re
import random
import asyncio
import time
import logging
import datetime
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
DAILY_REWARDS = {} # لتخزين وقت آخر مكافأة يومية

# إعدادات المزود
CURRENT_PROVIDER = "gemma"  # القيم المتاحة: 'gemma' أو 'google'
GOOGLE_API_KEYS = []
GOOGLE_MODEL_NAME = "gemini-2.5-flash" 

# إحصائيات
BOT_STATS = {
    "total_users": set(),
    "messages_count": 0,
    "start_time": time.time(),
    "user_activity": {} # لتخزين عدد رسائل كل مستخدم
}

# ==========================================
# النصوص التوجيهية (Prompts) - تم التعديل
# ==========================================

RPG_SYSTEM_PROMPT = """
أنت "ZEUS"، راوي قصص تفاعلية (Dungeon Master) عربي بالكامل.
تعليمات صارمة جداً:
1. **اللغة:** تحدث باللغة العربية الفصحى **فقط**. يمنع منعاً باتاً استخدام أي كلمة إنجليزية (مثال: لا تقل Status قل "الحالة"، لا تقل Inventory قل "الحقيبة"، لا تقل System قل "النظام").
2. **الأسلوب:** استخدم لغة بسيطة، واضحة، ومباشرة. تجنب المفردات الأدبية المعقدة والثقيلة إلا في وصف المعارك الملحمية جداً. اجعل كلامك مفهوماً للجميع.
3. **التنسيق:** استخدم **الخط العريض** للعناوين والأسماء المهمة.
4. **الخيارات:** في نهاية كل رد، اعرض 3-4 خيارات مرقمة لاتخاذ قرار.
5. **النوع:** القصة من نوع {genre}.
6. **البداية:** اللاعب يبدأ كـ {start_type}.
7. لا تقرر عن اللاعب، اعرض الموقف وانتظر رده.
"""

CHAT_SYSTEM_PROMPT = """
أنت "ZEUS"، مساعد ذكي عربي متطور.
القواعد:
1. تحدث باللغة العربية دائماً وبشكل طبيعي.
2. لا تستخدم مصطلحات إنجليزية إلا إذا طلب المستخدم كود برمجي أو شرح مصطلح تقني.
3. كن مختصراً ومفيداً.
4. استخدم التنسيق (نقاط، خط عريض) لتسهيل القراءة.
"""

# ==========================================
# دوال المساعدة والاتصال (Backend Logic)
# ==========================================

def clean_markdown(text):
    """
    تنظيف النص وإصلاح مشاكل التنسيق لتيليجرام.
    يقوم هذا الكود بإصلاح النجوم المكسورة ويسمح بمرور التنسيق الصحيح.
    """
    if not text:
        return ""
    
    # تحويل النجوم الغريبة إلى تنسيق Markdown صالح
    # أحياناً الذكاء الاصطناعي يضع مسافات داخل التغميق مثل ** نص ** وهذا خطأ
    text = re.sub(r'\*\*\s+(.*?)\s+\*\*', r'*\1*', text)
    
    # إصلاح الأقواس والرموز التي تربك تيليجرام
    # تيليجرام في وضع Markdown V1 يحتاج عناية خاصة
    # سنقوم بتبديل الرموز الحساسة إذا لم تكن جزءاً من كود
    
    # استبدال الرموز الإنجليزية بمرادفات إذا ظهرت (كحماية إضافية)
    text = text.replace('Inventory', 'الحقيبة').replace('Status', 'الحالة').replace('HP', 'نقاط الحياة')
    
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
                try:
                    raw_text = "".join(re.findall(r'\d+:"([^"]*)"', response.text))
                    cleaned_text = raw_text.replace('\\n', '\n').replace('\\"', '"').strip()
                    if cleaned_text:
                        return clean_markdown(cleaned_text)
                except:
                    pass
                return "⚠️ حدث خطأ بسيط في المعالجة، حاول مرة أخرى."
        except Exception as e:
            logger.error(f"Gemma Error: {e}")
            time.sleep(1)
    return "❌ الخادم مشغول حالياً، يرجى المحاولة لاحقاً."

# --- دالة الاتصال بـ Google Gemini ---
def ask_google(messages_list, retries=3):
    if not GOOGLE_API_KEYS:
        return "⚠️ النظام يحتاج إلى مفاتيح API (يرجى مراجعة الإدارة)."
    
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
            "temperature": 0.7, # تقليل الإبداع قليلاً لجعل الكلام أكثر دقة
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
            elif response.status_code == 429:
                api_key = random.choice(GOOGLE_API_KEYS)
                time.sleep(2)
                continue
            else:
                logger.error(f"Google Error: {response.status_code}")
        except Exception as e:
            logger.error(f"Google Connection Error: {e}")
            time.sleep(1)
            
    return "❌ تعذر الاتصال بخوادم Google."

# --- الموجه الذكي الموحد ---
def ask_ai_unified(messages_list):
    if CURRENT_PROVIDER == "google":
        return ask_google(messages_list)
    else:
        return ask_gemma(messages_list)

# --- أدوات الواجهة ---
def create_numeric_keyboard(text):
    """إنشاء لوحة مفاتيح ديناميكية"""
    options_indices = re.findall(r'(\d+)\.', text)
    buttons = []
    
    if options_indices:
        unique_options = sorted(list(set(options_indices)), key=int)
        row = []
        for opt in unique_options:
            row.append(KeyboardButton(opt))
            if len(row) == 4:
                buttons.append(row)
                row = []
        if row:
            buttons.append(row)
    
    buttons.append([KeyboardButton("📝 كتابة رد حر"), KeyboardButton("🔄 محاولة أخرى")])
    buttons.append([KeyboardButton("🏠 القائمة الرئيسية")])
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)

async def send_smart_message(update, text, reply_markup=None):
    """إرسال الرسائل مع محاولة إصلاح التنسيق في حالة الفشل"""
    max_length = 4000
    parts = [text[i:i+max_length] for i in range(0, len(text), max_length)]
    
    for i, part in enumerate(parts):
        markup = reply_markup if i == len(parts) - 1 else None
        try:
            # المحاولة الأولى: Markdown
            await update.message.reply_text(part, parse_mode=ParseMode.MARKDOWN, reply_markup=markup)
        except Exception as e:
            # إذا فشل التنسيق، نحاول إرساله كنص عادي للحفاظ على المحتوى
            logger.warning(f"Markdown failed: {e}. Sending plain text.")
            try:
                await update.message.reply_text(part, reply_markup=markup) # بدون parse_mode
            except:
                 await update.message.reply_text("❌ حدث خطأ في عرض الرسالة.", reply_markup=markup)

# ==========================================
# قوائم وأزرار التنقل (UI/UX)
# ==========================================

async def show_main_menu(update: Update):
    user = update.effective_user
    welcome_text = (
        f"👋 **أهلاً بك يا {user.first_name}**\n\n"
        "أنا ZEUS، بوابتك لعوالم الخيال والمساعد الذكي.\n"
        "اختر ماذا تريد أن تفعل الآن:"
    )
    
    keyboard = [
        [KeyboardButton("⚔️ ابدأ مغامرة (RPG)"), KeyboardButton("💬 مساعد ذكي")],
        [KeyboardButton("🏰 ملفي الشخصي"), KeyboardButton("🎁 الهدية اليومية")],
        [KeyboardButton("ℹ️ حول البوت")]
    ]
    
    if user.username == ADMIN_USERNAME:
        keyboard.append([KeyboardButton("⚙️ لوحة الإدارة")])

    markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text(clean_markdown(welcome_text), parse_mode=ParseMode.MARKDOWN, reply_markup=markup)

async def show_rpg_genres(update: Update):
    text = "🎭 **اختر عالم القصة:**"
    keyboard = [
        [KeyboardButton("🐉 أساطير شرقية"), KeyboardButton("🧙‍♂️ فانتازيا وسحر")],
        [KeyboardButton("🧟 نهاية العالم"), KeyboardButton("🚀 خيال علمي وفضاء")],
        [KeyboardButton("🕵️ غموض وتحقيق"), KeyboardButton("🏯 حروب الساموراي")],
        [KeyboardButton("🎲 عالم عشوائي"), KeyboardButton("🏠 القائمة الرئيسية")]
    ]
    markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=markup)

async def show_start_types(update: Update):
    text = "✨ **كيف تريد أن تبدأ؟**"
    keyboard = [
        [KeyboardButton("👑 ملك أو زعيم"), KeyboardButton("🗑️ فقير ومعدم")],
        [KeyboardButton("🤖 لدي نظام خارق"), KeyboardButton("🧠 عبقري وتكتيكي")],
        [KeyboardButton("⚔️ محارب قوي"), KeyboardButton("🎲 اختيار القدر")],
        [KeyboardButton("🔙 رجوع")]
    ]
    markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=markup)

async def show_chat_menu(update: Update):
    text = "💬 **المساعد الذكي**\nاسألني أي شيء أو اطلب مني المساعدة."
    keyboard = [
        [KeyboardButton("🧹 مسح الذاكرة")],
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
    users_count = len(BOT_STATS['total_users'])
    
    status_text = (
        "⚙️ **لوحة التحكم**\n"
        f"👥 المستخدمين: `{users_count}`\n"
        f"📡 المزود: **{CURRENT_PROVIDER}**\n"
        f"🔑 المفاتيح: `{len(GOOGLE_API_KEYS)}`\n"
        f"⏱️ العمل منذ: `{uptime} دقيقة`"
    )
    
    keyboard = [
        [KeyboardButton("➕ إضافة مفاتيح"), KeyboardButton("🔄 تبديل المزود")],
        [KeyboardButton("📢 إذاعة عامة"), KeyboardButton("🗑️ حذف المفاتيح")],
        [KeyboardButton("🏠 خروج")]
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
    user_first_name = update.effective_user.first_name
    
    # تحديث الإحصائيات
    BOT_STATS['total_users'].add(chat_id)
    BOT_STATS['messages_count'] += 1
    if chat_id not in BOT_STATS['user_activity']:
        BOT_STATS['user_activity'][chat_id] = 0
    BOT_STATS['user_activity'][chat_id] += 1

    # --- التنقل العام ---
    if text in ["🏠 القائمة الرئيسية", "🏠 خروج"]:
        CHAT_HISTORY[chat_id] = []
        USER_STATE[chat_id] = "MENU"
        await show_main_menu(update)
        return

    # --- أدوات الأدمن ---
    if text == "⚙️ لوحة الإدارة" and username == ADMIN_USERNAME:
        USER_STATE[chat_id] = "ADMIN_PANEL"
        await show_admin_panel(update)
        return

    if USER_STATE.get(chat_id) == "ADMIN_PANEL":
        if text == "🔄 تبديل المزود":
            global CURRENT_PROVIDER
            CURRENT_PROVIDER = "google" if CURRENT_PROVIDER == "gemma" else "gemma"
            await update.message.reply_text(f"✅ تم التبديل إلى: **{CURRENT_PROVIDER}**", parse_mode=ParseMode.MARKDOWN)
            await show_admin_panel(update)
            return
        
        elif text == "📢 إذاعة عامة":
            USER_STATE[chat_id] = "ADMIN_BROADCAST"
            await update.message.reply_text("📢 **أرسل الرسالة التي تريد نشرها للجميع الآن:**", parse_mode=ParseMode.MARKDOWN)
            return
            
        elif text == "➕ إضافة مفاتيح":
            USER_STATE[chat_id] = "ADMIN_WAITING_KEY"
            await update.message.reply_text("📥 أرسل المفاتيح (كل مفتاح في سطر):", parse_mode=ParseMode.MARKDOWN)
            return

        elif text == "🗑️ حذف المفاتيح":
            GOOGLE_API_KEYS.clear()
            await update.message.reply_text("🗑️ تم حذف المفاتيح.")
            await show_admin_panel(update)
            return

    # --- منطق الإذاعة (جديد) ---
    if USER_STATE.get(chat_id) == "ADMIN_BROADCAST" and username == ADMIN_USERNAME:
        msg_count = 0
        failed_count = 0
        processing_msg = await update.message.reply_text("⏳ جاري الإرسال...")
        
        for user_id in list(BOT_STATS['total_users']):
            if user_id == chat_id: continue
            try:
                await context.bot.send_message(chat_id=user_id, text=f"📢 **إعلان هام:**\n\n{text}", parse_mode=ParseMode.MARKDOWN)
                msg_count += 1
            except:
                failed_count += 1
        
        await processing_msg.edit_text(f"✅ تمت الإذاعة.\nتم الاستلام: {msg_count}\nفشل: {failed_count}")
        USER_STATE[chat_id] = "ADMIN_PANEL"
        await show_admin_panel(update)
        return

    if USER_STATE.get(chat_id) == "ADMIN_WAITING_KEY" and username == ADMIN_USERNAME:
        raw_keys = text.splitlines()
        added_count = 0
        for key in raw_keys:
            if len(key.strip()) > 20: 
                GOOGLE_API_KEYS.append(key.strip())
                added_count += 1
        
        await update.message.reply_text(f"✅ تمت إضافة {added_count} مفتاح.", parse_mode=ParseMode.MARKDOWN)
        USER_STATE[chat_id] = "ADMIN_PANEL"
        await show_admin_panel(update)
        return

    # --- الميزات الجديدة للمستخدم ---
    if text == "🎁 الهدية اليومية":
        today = datetime.date.today()
        last_claim = DAILY_REWARDS.get(chat_id)
        
        if last_claim == today:
            await update.message.reply_text("⚠️ لقد استلمت هديتك اليوم بالفعل! عد غداً.")
        else:
            DAILY_REWARDS[chat_id] = today
            reward = random.randint(10, 100)
            await update.message.reply_text(f"🎉 **مبروك!** حصلت على {reward} نقطة ذهبية!", parse_mode=ParseMode.MARKDOWN)
        return

    if text == "🏰 ملفي الشخصي":
        msg_count = BOT_STATS['user_activity'].get(chat_id, 0)
        
        # نظام رتب بسيط
        rank = "مغامر مبتدئ 🌱"
        if msg_count > 50: rank = "محارب متمرس ⚔️"
        if msg_count > 150: rank = "قائد أسطوري 👑"
        if msg_count > 500: rank = "حاكم العوالم 🐲"

        profile_msg = (
            "🏰 **بطاقة اللاعب** 🏰\n"
            "──────────────\n"
            f"👤 **الاسم:** {user_first_name}\n"
            f"🆔 **المعرف:** `{chat_id}`\n"
            f"🎖️ **الرتبة:** {rank}\n"
            f"📨 **الرسائل:** {msg_count}\n"
            f"🎭 **الوضع:** {USER_STATE.get(chat_id, 'قائمة')}\n"
            "──────────────"
        )
        await update.message.reply_text(profile_msg, parse_mode=ParseMode.MARKDOWN)
        return

    # --- اختيار الأوضاع ---
    if text == "⚔️ ابدأ مغامرة (RPG)":
        USER_STATE[chat_id] = "RPG_SELECT_GENRE"
        await show_rpg_genres(update)
        return
    
    if text == "💬 مساعد ذكي":
        USER_STATE[chat_id] = "CHAT_MODE"
        CHAT_HISTORY[chat_id] = [{"role": "user", "content": CHAT_SYSTEM_PROMPT}, {"role": "model", "content": "أهلاً! أنا جاهز لمساعدتك."}]
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
        if text == "🔙 رجوع":
            USER_STATE[chat_id] = "RPG_SELECT_GENRE"
            await show_rpg_genres(update)
            return

        start_type = text.strip()
        genre = USER_CONTEXT[chat_id].get("genre", "خيال")
        
        prompt = RPG_SYSTEM_PROMPT.format(genre=genre, start_type=start_type)
        CHAT_HISTORY[chat_id] = [{"role": "user", "content": prompt}]
        
        USER_STATE[chat_id] = "RPG_GAME"
        await process_ai_response(update, chat_id, text=None, is_rpg=True)
        return

    if USER_STATE.get(chat_id) == "RPG_GAME":
        if text == "📝 كتابة رد حر":
            await update.message.reply_text("⌨️ اكتب ما تريد فعله:")
            return
        if text == "🔄 محاولة أخرى":
            if len(CHAT_HISTORY[chat_id]) > 1:
                if CHAT_HISTORY[chat_id][-1]["role"] == "model":
                    CHAT_HISTORY[chat_id].pop()
                await process_ai_response(update, chat_id, text=None, is_rpg=True)
            return

        await process_ai_response(update, chat_id, text, is_rpg=True)
        return

    # --- منطق الدردشة ---
    if USER_STATE.get(chat_id) == "CHAT_MODE":
        if text == "🧹 مسح الذاكرة":
            CHAT_HISTORY[chat_id] = [{"role": "user", "content": CHAT_SYSTEM_PROMPT}]
            await update.message.reply_text("🧹 **تمت إعادة ضبط المحادثة.**", parse_mode=ParseMode.MARKDOWN)
            return
        
        await process_ai_response(update, chat_id, text, is_rpg=False)
        return
        
    if text == "ℹ️ حول البوت":
        await update.message.reply_text("🤖 **ZEUS AI**\nبوت ترفيهي وخدمي يعمل بالذكاء الاصطناعي.\nالنسخة العربية المحسنة V5.")
        return

    if USER_STATE.get(chat_id) == "MENU":
        await show_main_menu(update)

# ==========================================
# معالجة الردود (AI Processor)
# ==========================================
async def process_ai_response(update, chat_id, text, is_rpg):
    """دالة مركزية لمعالجة وإرسال ردود الذكاء الاصطناعي"""
    
    if text:
        CHAT_HISTORY[chat_id].append({"role": "user", "content": text})
    
    # إدارة الذاكرة
    max_history = 16 if is_rpg else 10
    if len(CHAT_HISTORY[chat_id]) > max_history:
        system_msg = CHAT_HISTORY[chat_id][0]
        recent_msgs = CHAT_HISTORY[chat_id][-(max_history-1):]
        CHAT_HISTORY[chat_id] = [system_msg] + recent_msgs

    await update.effective_chat.send_action(ChatAction.TYPING)

    loop = asyncio.get_running_loop()
    bot_reply = await loop.run_in_executor(None, ask_ai_unified, CHAT_HISTORY[chat_id])
    
    CHAT_HISTORY[chat_id].append({"role": "model", "content": bot_reply})
    
    markup = create_numeric_keyboard(bot_reply) if is_rpg else None
    if not is_rpg:
        markup = ReplyKeyboardMarkup([[KeyboardButton("🧹 مسح الذاكرة"), KeyboardButton("🏠 القائمة الرئيسية")]], resize_keyboard=True)

    await send_smart_message(update, bot_reply, reply_markup=markup)

# ==========================================
# تشغيل البوت
# ==========================================
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    CHAT_HISTORY[chat_id] = []
    USER_STATE[chat_id] = "MENU"
    await show_main_menu(update)

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error(msg="Exception while handling an update:", exc_info=context.error)

if __name__ == "__main__":
    print("🚀 ZEUS AI (V5.0 Arabic Edition) is Starting...")
    print(f"📡 Provider: {CURRENT_PROVIDER}")
    
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("admin", show_admin_panel))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_error_handler(error_handler)

    print("✅ Bot is Online & Ready!")
    app.run_polling()