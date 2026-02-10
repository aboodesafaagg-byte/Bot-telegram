import requests
import re
import random
import asyncio
import time
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from telegram.constants import ChatAction, ParseMode
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

# ==========================================
# ضع التوكن الخاص بك هنا
BOT_TOKEN = "8321203989:AAFCZTJx4mYM6DPSy9kQGixSy7XC22ZxmWk"
# ==========================================

# إعدادات الذاكرة
CHAT_HISTORY = {}

# هذا هو "القلب" الذي يحول البوت إلى لعبة.
# نقوم بتعليم الذكاء الاصطناعي كيف يتصرف بدقة صارمة.
SYSTEM_PROMPT = """
أنت "راوي قصص تفاعلية" (Dungeon Master) محترف.
قوانين اللعبة الصارمة:
1. تحدث باللغة العربية بأسلوب قصصي مشوق.
2. مهمتك هي وصف المشهد الحالي للمستخدم، ثم التوقف وانتظار قراره.
3. في نهاية كل رد، يجب أن تعطي المستخدم بين 2 إلى 4 خيارات لاتخاذ القرار التالي.
4. يجب كتابة الخيارات بصيغة قائمة مرقمة واضحة جداً، كل خيار في سطر جديد، مثال:
   1. أهاجم الوحش بالسيف.
   2. أهرب واختبئ خلف الصخرة.
   3. أحاول التفاوض معه.
5. لا تقم أبداً باتخاذ القرار نيابة عن المستخدم.
6. إذا مات اللاعب أو انتهت القصة، اكتب عبارة "انتهت اللعبة" بوضوح.
"""

# ---------------------------------------------------------
# دالة الاتصال بالموقع (نفس الدالة القوية التي طلبناها)
# ---------------------------------------------------------
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
                # تنظيف النص القادم من البث (Stream)
                raw_text = "".join(re.findall(r'\d+:"([^"]*)"', response.text))
                cleaned_text = raw_text.replace('\\n', '\n').replace('\\"', '"').strip()
                return cleaned_text if cleaned_text else "⚠️ حدث خطأ: وصل رد فارغ من الراوي."
        except Exception as e:
            print(f"Attempt {attempt+1} failed: {e}")
            time.sleep(2)
    
    return "❌ الخادم مشغول جداً، حاول الضغط على الخيار مرة أخرى."

# ---------------------------------------------------------
# دالة ذكية لاستخراج الخيارات من النص وتحويلها لأزرار
# ---------------------------------------------------------
def create_keyboard_from_text(text):
    # نبحث عن الأسطر التي تبدأ برقم ونقطة (مثل: 1. افعل كذا)
    # هذا التعبير النمطي يبحث عن رقم، ثم نقطة، ثم مسافة، ثم باقي النص
    options = re.findall(r'(\d+\..+)', text)
    
    if not options:
        # إذا لم نجد خيارات مرقمة، قد تكون اللعبة انتهت أو بداية جديدة
        # نعيد زر لبدء لعبة جديدة احتياطاً
        return ReplyKeyboardMarkup([["/start 🔄 لعبة جديدة"]], resize_keyboard=True)
    
    # تحويل الخيارات المستخرجة إلى أزرار
    # نجعل كل زر في سطر مستقل ليكون واضحاً
    keyboard_buttons = [[KeyboardButton(opt)] for opt in options]
    
    # إضافة زر "خروج" أو "بداية جديدة" دائماً في الأسفل
    keyboard_buttons.append([KeyboardButton("/new 🔄 قصة جديدة")])
    
    return ReplyKeyboardMarkup(keyboard_buttons, one_time_keyboard=False, resize_keyboard=True)

# ---------------------------------------------------------
# دالة تقسيم الرسائل الطويلة (معدلة لتقبل الأزرار)
# ---------------------------------------------------------
async def send_smart_message(update, text, reply_markup=None):
    max_length = 4000
    
    # إذا النص قصير، نرسله فوراً مع الأزرار
    if len(text) <= max_length:
        try:
            await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)
        except:
            # محاولة ثانية بدون ماركداون إذا فشل التنسيق
            await update.message.reply_text(text, reply_markup=reply_markup)
    else:
        # إذا النص طويل، نقسمه
        parts = [text[i:i+max_length] for i in range(0, len(text), max_length)]
        
        # نرسل كل الأجزاء ما عدا الأخير بدون أزرار
        for part in parts[:-1]:
            try:
                await update.message.reply_text(part, parse_mode=ParseMode.MARKDOWN)
            except:
                await update.message.reply_text(part)
        
        # الجزء الأخير فقط هو الذي يحتوي على الأزرار
        last_part = parts[-1]
        try:
            await update.message.reply_text(last_part, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)
        except:
            await update.message.reply_text(last_part, reply_markup=reply_markup)

# ---------------------------------------------------------
# دوال التحكم (Handlers)
# ---------------------------------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    CHAT_HISTORY[chat_id] = []
    
    # إعداد بداية القصة
    CHAT_HISTORY[chat_id].append({"role": "user", "content": SYSTEM_PROMPT + "\n\nابدأ اللعبة الآن. رحب بي، ثم اعرض علي 3 عوالم مختلفة (رعب، خيال علمي، تاريخي) لأختار منها."})
    
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    
    # جلب الرد الأول
    loop = asyncio.get_running_loop()
    bot_reply = await loop.run_in_executor(None, ask_gemma, CHAT_HISTORY[chat_id])
    
    # حفظ الرد
    CHAT_HISTORY[chat_id].append({"role": "assistant", "content": bot_reply})
    
    # إنشاء الأزرار بناءً على الرد
    markup = create_keyboard_from_text(bot_reply)
    
    await send_smart_message(update, bot_reply, reply_markup=markup)

async def new_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # نفس وظيفة Start، تبدأ لعبة جديدة
    await start(update, context)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_text = update.message.text
    
    # تجاهل الأوامر التي تبدأ بـ / هنا (يتم التعامل معها عبر handlers خاصة)
    if user_text.startswith('/'):
        return

    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

    # تهيئة الذاكرة إذا لم تكن موجودة
    if chat_id not in CHAT_HISTORY:
        CHAT_HISTORY[chat_id] = []
        CHAT_HISTORY[chat_id].append({"role": "user", "content": SYSTEM_PROMPT})
        CHAT_HISTORY[chat_id].append({"role": "assistant", "content": "أهلاً بك. اختر نوع المغامرة."})

    # إضافة خيار المستخدم للذاكرة
    CHAT_HISTORY[chat_id].append({"role": "user", "content": user_text})
    
    # إدارة حجم الذاكرة (نحتفظ بآخر 12 رسالة ليبقى البوت سريعاً وذكياً)
    # نحافظ دائماً على العنصر رقم 0 (System Prompt) لكي لا ينسى أنه راوي قصص
    if len(CHAT_HISTORY[chat_id]) > 14:
        system_msg = CHAT_HISTORY[chat_id][0]
        recent_msgs = CHAT_HISTORY[chat_id][-10:]
        CHAT_HISTORY[chat_id] = [system_msg] + recent_msgs

    # جلب رد الراوي (Gemma)
    loop = asyncio.get_running_loop()
    bot_reply = await loop.run_in_executor(None, ask_gemma, CHAT_HISTORY[chat_id])
    
    # حفظ رد الراوي
    CHAT_HISTORY[chat_id].append({"role": "assistant", "content": bot_reply})

    # إنشاء الأزرار الجديدة للموقف الجديد
    markup = create_keyboard_from_text(bot_reply)

    # إرسال الرد
    await send_smart_message(update, bot_reply, reply_markup=markup)

# ---------------------------------------------------------
# التشغيل الرئيسي
# ---------------------------------------------------------
if __name__ == "__main__":
    print("🚀 Bot Started (Game Mode)...")
    app = Application.builder().token(BOT_TOKEN).build()

    # الأوامر
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("new", new_game))
    
    # معالجة النصوص (الردود على اللعبة)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    app.run_polling()
