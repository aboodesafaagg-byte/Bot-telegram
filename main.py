import requests
import re
import random
import asyncio
import time
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from telegram.constants import ChatAction, ParseMode
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

# ==========================================
# إعدادات البوت والتوكن
# ==========================================
BOT_TOKEN = "8321203989:AAFCZTJx4mYM6DPSy9kQGixSy7XC22ZxmWk"

# ==========================================
# متغيرات النظام
# ==========================================
CHAT_HISTORY = {}
# حالة المستخدم (هل هو في القائمة الرئيسية أم داخل اللعبة)
USER_STATE = {} 

# النص التوجيهي للذكاء الاصطناعي (ZEUS AI)
SYSTEM_PROMPT = """
أنت "ZEUS AI"، راوي قصص تفاعلية (Dungeon Master) متطور جداً.
قواعدك الصارمة:
1. أنت لست مجرد بوت، أنت محرك قصصي.
2. مهمتك: سرد أحداث مشوقة جداً ووضع اللاعب في مواقف تتطلب الاختيار.
3. التنسيق مطلوب: استخدم الخط العريض للعناوين أو الأشياء المهمة بوضع نجمتين حول الكلمة (مثال: **المهمة**).
4. في نهاية كل رد، يجب أن تعطي اللاعب خيارات مرقمة واضحة (1. كذا، 2. كذا..).
5. لا تتخذ القرارات عن اللاعب، توقف وانتظر رده.
6. إذا اختار اللاعب رقماً، افهم سياق الرقم من رسالتك السابقة وأكمل القصة.
7. لا تستخدم الرموز الغريبة مثل الشرطات المائلة (\\) في الأسماء.
"""

# ==========================================
# الدوال المساعدة (Backend Logic)
# ==========================================

def clean_markdown(text):
    """
    دالة لإصلاح مشاكل التنسيق بين الذكاء الاصطناعي وتليجرام.
    تحول **نص** إلى *نص* وتزيل الرموز المزعجة.
    """
    # 1. إزالة الشرطات المائلة المزعجة (Artifacts)
    text = text.replace('\\', '')
    
    # 2. تحويل Bold من تنسيق Markdown القياسي (**) إلى تنسيق تليجرام القديم (*)
    # تليجرام في الوضع العادي يستخدم نجمة واحدة للتغميق
    text = text.replace('**', '*')
    
    # 3. حماية الرموز الخاصة التي قد تكسر الرسالة
    # (اختياري لكن مفيد إذا ظهرت مشاكل أخرى)
    return text

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

    payload = {
        "model": "gemma-3-27b",
        "messages": messages_list
    }

    for attempt in range(retries):
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=30)
            if response.status_code == 200:
                # استخراج النص وتنظيفه
                raw_text = "".join(re.findall(r'\d+:"([^"]*)"', response.text))
                
                # تنظيف أولي لرموز JSON
                cleaned_text = raw_text.replace('\\n', '\n').replace('\\"', '"').strip()
                
                # تنظيف إضافي للمشاكل التي ذكرتها (الشرطات والماركدون)
                final_text = clean_markdown(cleaned_text)
                
                return final_text if final_text else "⚠️ حدث خطأ تقني: وصل رد فارغ."
        except Exception as e:
            print(f"Attempt {attempt+1} failed: {e}")
            time.sleep(2)
    
    return "❌ الخادم لا يستجيب حالياً. الرجاء المحاولة مرة أخرى."

def create_numeric_keyboard(text):
    """
    تستخرج الخيارات من النص وتنشئ أزراراً تحتوي على الأرقام فقط (1، 2، 3).
    """
    # البحث عن أي سطر يبدأ برقم ونقطة (مثال: 1. اذهب يميناً)
    # نأخذ الرقم فقط
    options_indices = re.findall(r'(\d+)\.', text)
    
    # إزالة التكرار وترتيب الأرقام (لضمان ظهور 1، 2، 3 بشكل مرتب)
    # أحياناً يذكر الذكاء الاصطناعي أرقاماً في سياق الحديث، لذا نأخذ الحيطة
    # لكن غالباً القائمة تكون في النهاية.
    
    buttons = []
    if options_indices:
        # نأخذ الأرقام الفريدة فقط ونحولها لأزرار
        unique_options = sorted(list(set(options_indices)), key=int)
        
        # تنسيق الأزرار: كل زرين في صف، أو كل زر في صف
        row = []
        for opt in unique_options:
            row.append(KeyboardButton(opt))
            if len(row) == 2: # زرين في كل صف لجمالية أكثر
                buttons.append(row)
                row = []
        if row:
            buttons.append(row)
    
    # زر الخروج دائماً موجود للعودة للقائمة الرئيسية
    buttons.append([KeyboardButton("🏠 القائمة الرئيسية")])
    
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)

async def send_smart_message(update, text, reply_markup=None):
    max_length = 4000
    
    if len(text) <= max_length:
        try:
            # محاولة الإرسال بوضع الماركدون (للتغميق والجمالية)
            await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)
        except Exception as e:
            print(f"Markdown Error: {e}")
            # إذا فشل الماركدون، أرسل النص كما هو (بدون تنسيق) لتجنب توقف البوت
            await update.message.reply_text(text, reply_markup=reply_markup)
    else:
        # تقسيم الرسائل الطويلة
        parts = [text[i:i+max_length] for i in range(0, len(text), max_length)]
        for i, part in enumerate(parts):
            is_last = (i == len(parts) - 1)
            markup = reply_markup if is_last else None
            try:
                await update.message.reply_text(part, parse_mode=ParseMode.MARKDOWN, reply_markup=markup)
            except:
                await update.message.reply_text(part, reply_markup=markup)

# ==========================================
# دوال التعامل مع المستخدم (Handlers)
# ==========================================

async def show_main_menu(update: Update):
    """عرض القائمة الرئيسية"""
    welcome_text = (
        "⚡ **أهلاً بك في ZEUS AI** ⚡\n\n"
        "أنا لست مجرد بوت، أنا بوابتك لعوالم لا نهائية من الخيال.\n"
        "أقوم بتأليف قصص تفاعلية (RPG) وأنت البطل فيها.\n\n"
        "👇 **اختر من القائمة أدناه للبدء:**"
    )
    
    keyboard = [
        [KeyboardButton("⚔️ ابدأ مغامرة جديدة")],
        [KeyboardButton("ℹ️ كيف ألعب؟"), KeyboardButton("🤖 عن البوت")]
    ]
    markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    # تنظيف الماركدون للنص الترحيبي أيضاً
    await update.message.reply_text(clean_markdown(welcome_text), parse_mode=ParseMode.MARKDOWN, reply_markup=markup)

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    CHAT_HISTORY[chat_id] = [] # تصفير الذاكرة
    USER_STATE[chat_id] = "MENU" # تعيين الحالة: قائمة رئيسية
    await show_main_menu(update)

async def help_section(update: Update):
    text = (
        "ℹ️ **كيف تستخدم ZEUS AI؟**\n\n"
        "1. اضغط على 'بدء مغامرة جديدة'.\n"
        "2. سيقوم زيوس (الذكاء الاصطناعي) بسرد بداية القصة.\n"
        "3. في نهاية كل رسالة، ستجد خيارات مرقمة (مثل: 1. أهاجم، 2. أهرب).\n"
        "4. **اقرأ الخيارات من الرسالة**، ثم اضغط على **الرقم الموافق** في الأزرار بالأسفل.\n"
        "5. استمتع بالقصة! قراراتك تغير مجرى الأحداث."
    )
    await update.message.reply_text(clean_markdown(text), parse_mode=ParseMode.MARKDOWN)

async def about_section(update: Update):
    text = (
        "🤖 **عن ZEUS AI**\n\n"
        "هذا البوت يعمل بمحرك ذكاء اصطناعي متطور (Gemma 3).\n"
        "تم تصميمه ليكون 'راوي قصص' (Dungeon Master) يتذكر أحداث قصتك ويتفاعل مع قراراتك بذكاء."
    )
    await update.message.reply_text(clean_markdown(text), parse_mode=ParseMode.MARKDOWN)

async def start_game_logic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    USER_STATE[chat_id] = "GAME" # تغيير الحالة إلى: داخل اللعبة
    CHAT_HISTORY[chat_id] = [] # تصفير الذاكرة لبدء قصة نظيفة
    
    # إرسال التوجيه الأولي للذكاء الاصطناعي
    # نطلب منه أن يعرض أنواع القصص المتاحة
    initial_message = SYSTEM_PROMPT + "\n\nابدأ الآن. رحب باللاعب واعرض عليه 3 أنواع من القصص (رعب، خيال علمي، غموض) ليختار منها."
    CHAT_HISTORY[chat_id].append({"role": "user", "content": initial_message})
    
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    
    # جلب الرد الأول
    loop = asyncio.get_running_loop()
    bot_reply = await loop.run_in_executor(None, ask_gemma, CHAT_HISTORY[chat_id])
    
    CHAT_HISTORY[chat_id].append({"role": "assistant", "content": bot_reply})
    
    # إنشاء أزرار الأرقام
    markup = create_numeric_keyboard(bot_reply)
    await send_smart_message(update, bot_reply, reply_markup=markup)

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    text = update.message.text
    
    # 1. معالجة أزرار القائمة الرئيسية
    if text == "⚔️ ابدأ مغامرة جديدة":
        await start_game_logic(update, context)
        return
    elif text == "ℹ️ كيف ألعب؟":
        await help_section(update)
        return
    elif text == "🤖 عن البوت":
        await about_section(update)
        return
    elif text == "🏠 القائمة الرئيسية":
        CHAT_HISTORY[chat_id] = [] # مسح الذاكرة عند الخروج
        USER_STATE[chat_id] = "MENU"
        await show_main_menu(update)
        return

    # 2. معالجة اللعبة (إذا كان المستخدم داخل اللعبة)
    if USER_STATE.get(chat_id) == "GAME":
        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
        
        # إدارة الذاكرة (للحفاظ على الأداء)
        if chat_id not in CHAT_HISTORY:
             CHAT_HISTORY[chat_id] = [{"role": "user", "content": SYSTEM_PROMPT}]

        CHAT_HISTORY[chat_id].append({"role": "user", "content": text})
        
        # تقليص الذاكرة إذا طالت جداً (مع الحفاظ على التوجيه الأول)
        if len(CHAT_HISTORY[chat_id]) > 14:
            system_msg = CHAT_HISTORY[chat_id][0]
            recent_msgs = CHAT_HISTORY[chat_id][-10:]
            CHAT_HISTORY[chat_id] = [system_msg] + recent_msgs

        # الاتصال بالذكاء الاصطناعي
        loop = asyncio.get_running_loop()
        bot_reply = await loop.run_in_executor(None, ask_gemma, CHAT_HISTORY[chat_id])
        
        CHAT_HISTORY[chat_id].append({"role": "assistant", "content": bot_reply})
        
        # إنشاء الأزرار الرقمية للرد الجديد
        markup = create_numeric_keyboard(bot_reply)
        
        await send_smart_message(update, bot_reply, reply_markup=markup)
    else:
        # إذا أرسل نصاً وهو في القائمة الرئيسية (وليس أمراً)
        await update.message.reply_text("الرجاء استخدام الأزرار في القائمة، أو اضغط 'بدء مغامرة جديدة'.")

# ==========================================
# التشغيل الرئيسي
# ==========================================
if __name__ == "__main__":
    print("🚀 ZEUS AI is Running...")
    
    app = Application.builder().token(BOT_TOKEN).build()

    # الأوامر الأساسية
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("new", start_command)) # اختصار للعودة
    
    # معالجة النصوص (الأزرار واللعب)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    app.run_polling()
