import logging
import os
import re
import json
import asyncio
import random
import requests  # للمزود Gemma القديم
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, ReplyKeyboardRemove, ChatAction
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
import google.generativeai as genai
from collections import deque

# ------------------- التكوين والتوكنات -------------------
# ضع توكن البوت هنا
TOKEN = os.getenv("BOT_TOKEN", "8292364018:AAEvovWMM0kUb7d_GpW-6JV-U34Xz0usJPQ")

# قائمة مفاتيح جوجل (سيتم تعبئتها من البوت أو المتغيرات)
GOOGLE_KEYS = []
current_key_index = 0  # لتتبع المفتاح الحالي

# إعدادات التسجيل (Log)
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# ------------------- دوال التخزين (قاعدة البيانات البسيطة) -------------------
USERS_DB = "users_db.json"

def load_db():
    try:
        if os.path.exists(USERS_DB):
            with open(USERS_DB, 'r', encoding='utf-8') as f:
                return json.load(f)
    except:
        pass
    return {"users": {}, "settings": {"provider": "google"}} # الافتراضي

def save_db(db):
    with open(USERS_DB, 'w', encoding='utf-8') as f:
        json.dump(db, f, ensure_ascii=False, indent=4)

db = load_db()

# ------------------- 1. دالة Gemma (الطريقة القديمة - Scraping) -------------------
def ze_gemma_old(m):
    """
    تستخدم الطريقة القديمة عبر requests لموقع gemma3.cc
    بدون مفاتيح API رسمية.
    """
    try:
        # محاكاة متصفح حقيقي
        headers = {
            "User-Agent": random.choice([
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.1.1 Safari/605.1.15",
                "Mozilla/5.0 (Linux; Android 10; SM-A205U) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.120 Mobile Safari/537.36"
            ]),
            "Content-Type": "application/json",
            "Referer": "https://gemma3.cc/"
        }
        
        payload = {
            "model": "gemma-3-27b",
            "messages": [{"role": "user", "content": m}]
        }

        r = requests.post("https://gemma3.cc/api/chat", json=payload, headers=headers, timeout=20)
        
        if r.status_code == 200:
            # تنظيف الرد باستخدام Regex كما في الكود القديم
            t = "".join(re.findall(r'\d+:"([^"]*)"', r.text))
            cleaned = t.replace('\\n', '\n').replace('\\"', '"').strip()
            return cleaned if cleaned else "⚠️ وصل رد فارغ من Gemma."
        else:
            return f"⚠️ خطأ من المصدر: {r.status_code}"
    except Exception as e:
        return f"⚠️ خطأ في الاتصال بـ Gemma: {e}"

# ------------------- 2. دالة Google (مع تدوير المفاتيح) -------------------
async def get_google_response_rotated(history):
    """
    تحاول الإرسال باستخدام المفتاح الحالي، إذا فشل تجرب التالي، وهكذا.
    """
    global current_key_index, GOOGLE_KEYS
    
    if not GOOGLE_KEYS:
        return "⚠️ لا توجد مفاتيح Google محفوظة! استخدم /key لإضافة مفاتيح."

    # محاولة الدوران على المفاتيح بعددها
    attempts = 0
    max_attempts = len(GOOGLE_KEYS)

    while attempts < max_attempts:
        key = GOOGLE_KEYS[current_key_index]
        try:
            genai.configure(api_key=key)
            # نستخدم النموذج الفلاش السريع (1.5 هو المستقر حالياً بدلاً من 2.5 غير الموجود)
            model = genai.GenerativeModel('gemini-2.5-flash')
            
            # تحويل التاريخ لصيغة جوجل
            google_history = []
            for msg in history:
                role = "user" if msg['role'] == "user" else "model"
                google_history.append({"role": role, "parts": [msg['content']]})
            
            # نفترض أن آخر رسالة هي السؤال، والباقي تاريخ
            chat = model.start_chat(history=google_history[:-1])
            response = await chat.send_message_async(google_history[-1]['parts'][0])
            
            return response.text
            
        except Exception as e:
            error_str = str(e)
            logger.error(f"Key ending in ...{key[-5:]} failed: {error_str}")
            
            # إذا كان الخطأ 429 (Too Many Requests) أو خطأ مصادقة، نبدل المفتاح
            if "429" in error_str or "403" in error_str or "quota" in error_str.lower():
                # الانتقال للمفتاح التالي
                current_key_index = (current_key_index + 1) % len(GOOGLE_KEYS)
                attempts += 1
                continue # إعادة المحاولة بالمفتاح الجديد
            else:
                # خطأ آخر لا علاقة له بالمفتاح (مثل المحتوى الممنوع)
                return f"⚠️ خطأ غير متعلق بالمفتاح: {error_str}"

    return "❌ فشلت جميع المفاتيح المتوفرة (429 Quota Exceeded). يرجى إضافة مفاتيح جديدة."

# ------------------- منطق البوت والقصص -------------------

# (نفس منطق القصص السابق لضمان عمل الأزرار)
STORY_DATA = {
    "start": {
        "text": "🌌 *بداية المهمة: بروتوكول أوميغا*\n\nتستيقظ في كبسولة تجميد. الإنذارات تضوي باللون الأحمر. الذاكرة مشوشة.",
        "options": [
            {"text": "🔍 فحص الحاسوب", "next": "check_pc"},
            {"text": "🏃 الهروب فوراً", "next": "escape_pod"}
        ]
    },
    "check_pc": {
        "text": "تفتح السجلات. ترى تحذيراً: 'اكتشاف كائن غريب في القطاع 7'. تسمع صوتاً خلفك...",
        "options": [
            {"text": "🔫 استعد للقتال", "next": "fight"},
            {"text": "🗣️ حاول التواصل", "next": "talk"}
        ]
    },
    "escape_pod": {
        "text": "تركض نحو كبسولات النجاة. لكن الباب مغلق ويتطلب رمزاً أمنياً.",
        "options": [
            {"text": "💻 اختراق الباب", "next": "hack_door"},
            {"text": "🔨 كسر القفل", "next": "break_lock"}
        ]
    },
    # نهايات بسيطة للتجربة
    "fight": {"text": "🔚 المجهول كان أقوى منك. انتهت القصة. /story للبدء مجدداً.", "options": []},
    "talk": {"text": "🔚 الكائن كان ودوداً وأرشدك للمخرج. نجوت! /story للبدء مجدداً.", "options": []},
    "hack_door": {"text": "🔚 فتحت الباب ونجوت في اللحظة الأخيرة. /story للبدء مجدداً.", "options": []},
    "break_lock": {"text": "🔚 انطلق الإنذار الأمني وتم القبض عليك. /story للبدء مجدداً.", "options": []}
}

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    uid = str(user.id)
    
    if uid not in db["users"]:
        db["users"][uid] = {"mode": "chat", "history": []}
        save_db(db)

    keyboard = [
        [InlineKeyboardButton("💬 وضع الدردشة", callback_data="mode_chat"),
         InlineKeyboardButton("📖 قصة تفاعلية", callback_data="mode_story")],
        [InlineKeyboardButton("⚙️ لوحة التحكم", callback_data="admin_panel")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"⚡ **أهلاً بك في ZEUS AI** ⚡\n\nأنا مساعدك الذكي وراوي قصصك المفضل.\n💎 **المزود الحالي:** {db['settings']['provider'].upper()}\n👇 **ماذا تريد أن تفعل اليوم؟**",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    uid = str(query.from_user.id)

    if data == "mode_chat":
        db["users"][uid]["mode"] = "chat"
        save_db(db)
        await query.edit_message_text("💬 **أنت الآن في وضع الدردشة الحرة.**\nتحدث معي بشكل طبيعي!")

    elif data == "mode_story":
        db["users"][uid]["mode"] = "story"
        db["users"][uid]["story_node"] = "start"
        save_db(db)
        # بدء القصة
        node = STORY_DATA["start"]
        buttons = [[InlineKeyboardButton(opt["text"], callback_data=f"story:{opt['next']}")] for opt in node["options"]]
        await query.edit_message_text(node["text"], reply_markup=InlineKeyboardMarkup(buttons))

    elif data.startswith("story:"):
        next_node_key = data.split(":")[1]
        node = STORY_DATA.get(next_node_key, STORY_DATA["start"])
        
        buttons = []
        if node["options"]:
            buttons = [[InlineKeyboardButton(opt["text"], callback_data=f"story:{opt['next']}")] for opt in node["options"]]
        
        await query.edit_message_text(node["text"], reply_markup=InlineKeyboardMarkup(buttons))

    elif data == "admin_panel":
        if str(query.from_user.id) not in db["users"]: # يمكن تقييدها بالآدمن الحقيقي
             pass 
        
        count = len(db["users"])
        provider = db["settings"]["provider"]
        keys_count = len(GOOGLE_KEYS)
        
        text = (
            f"⚙️ **لوحة تحكم المدير (Zeus Control)**\n\n"
            f"📊 عدد المستخدمين: {count}\n"
            f"📡 المزود الحالي: **{provider}**\n"
            f"🔑 عدد مفاتيح Google: {keys_count}\n\n"
            "لتبديل المزود اضغط أدناه:"
        )
        buttons = [
            [InlineKeyboardButton("Gemma (مجاني/قديم)", callback_data="set_gemma"),
             InlineKeyboardButton("Google (رسمي/مفاتيح)", callback_data="set_google")],
            [InlineKeyboardButton("🔙 عودة", callback_data="mode_chat")]
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode="Markdown")

    elif data == "set_gemma":
        db["settings"]["provider"] = "gemma"
        save_db(db)
        await query.answer("تم التبديل إلى Gemma (النظام القديم) ✅")
        await handle_callback(update, context) # تحديث اللوحة

    elif data == "set_google":
        db["settings"]["provider"] = "google"
        save_db(db)
        await query.answer("تم التبديل إلى Google API ✅")
        await handle_callback(update, context) # تحديث اللوحة

async def add_key_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    أمر لإضافة مفاتيح API. يقبل أسطر متعددة.
    """
    text = update.message.text.replace("/key", "").strip()
    
    if not text:
        await update.message.reply_text("❌ الرجاء إرسال المفاتيح بعد الأمر.\nمثال:\n/key AIzaSy...\nAIzaSy2...")
        return

    # تقسيم النص إلى أسطر وتنظيف الفراغات
    new_keys = [k.strip() for k in text.split('\n') if k.strip()]
    
    if not new_keys:
        return

    global GOOGLE_KEYS
    GOOGLE_KEYS.extend(new_keys)
    
    await update.message.reply_text(f"✅ تم إضافة {len(new_keys)} مفتاح/مفاتيح بنجاح!\nالعدد الكلي الآن: {len(GOOGLE_KEYS)}")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_msg = update.message.text
    uid = str(update.effective_user.id)
    
    # التأكد من وجود المستخدم في قاعدة البيانات
    if uid not in db["users"]:
        db["users"][uid] = {"mode": "chat", "history": []}

    mode = db["users"][uid].get("mode", "chat")

    # إذا كان في وضع القصة، نتجاهل النص (يعتمد على الأزرار) أو نحوله لدردشة
    if mode == "story":
        await update.message.reply_text("⚠️ أنت في وضع القصة. استخدم الأزرار أو اضغط /start للخروج.")
        return

    # إظهار "جاري الكتابة..."
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)

    # تجهيز التاريخ (لجوجل فقط، جيما القديم لا يدعم الذاكرة الطويلة جيداً بهذه الطريقة)
    history = db["users"][uid]["history"]
    history.append({"role": "user", "content": user_msg})
    # نحتفظ بآخر 10 رسائل فقط للذاكرة
    if len(history) > 10: 
        history = history[-10:]

    provider = db["settings"]["provider"]
    response_text = ""

    if provider == "gemma":
        # 🟢 استخدام الطريقة القديمة (بدون مفاتيح)
        # تشغيل الدالة في Thread منفصل لعدم تجميد البوت
        loop = asyncio.get_running_loop()
        # نرسل فقط آخر رسالة لأن النظام القديم لا يدعم التاريخ المعقد
        response_text = await loop.run_in_executor(None, ze_gemma_old, user_msg)
    
    else:
        # 🔵 استخدام Google API (مع التدوير)
        response_text = await get_google_response_rotated(history)

    # حفظ الرد في التاريخ
    history.append({"role": "model", "content": response_text})
    db["users"][uid]["history"] = history
    save_db(db)

    await update.message.reply_text(response_text, parse_mode=None) # parse_mode=None لتجنب أخطاء التنسيق

async def new_story_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # اختصار لبدء القصة
    uid = str(update.effective_user.id)
    db["users"][uid]["mode"] = "story"
    db["users"][uid]["story_node"] = "start"
    save_db(db)
    
    node = STORY_DATA["start"]
    buttons = [[InlineKeyboardButton(opt["text"], callback_data=f"story:{opt['next']}")] for opt in node["options"]]
    await update.message.reply_text(node["text"], reply_markup=InlineKeyboardMarkup(buttons))

# ------------------- التشغيل الرئيسي -------------------
def main():
    print("🚀 ZEUS AI (Hybrid V4) is Running...")
    
    app = Application.builder().token(TOKEN).build()

    # الأوامر
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("key", add_key_command)) # إضافة المفاتيح
    app.add_handler(CommandHandler("new", new_story_command))
    
    # المعالجات
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    # اكتشاف البيئة (Railway vs Local)
    if "PORT" in os.environ:
        port = int(os.environ.get("PORT", "8080"))
        webhook_url = os.environ.get("RAILWAY_PUBLIC_DOMAIN") # أو رابطك الخاص
        if webhook_url:
            if not webhook_url.startswith("https://"):
                webhook_url = "https://" + webhook_url
            app.run_webhook(
                listen="0.0.0.0",
                port=port,
                url_path=TOKEN,
                webhook_url=f"{webhook_url}/{TOKEN}"
            )
        else:
            # حالة نادرة في railway بدون دومين
            app.run_polling()
    else:
        # تشغيل محلي
        app.run_polling()

if __name__ == "__main__":
    import nest_asyncio
    nest_asyncio.apply()
    main()