
# -*- coding: utf-8 -*-
import os
import time
import re
import json
import logging
import telegram
from datetime import datetime
from collections import defaultdict
from flask import Flask, request
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, ChatMemberHandler, filters
from telegram.error import BadRequest
from telegram.constants import ParseMode

# إعداد التسجيل
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# إنشاء تطبيق Flask للـ webhook
app = Flask(__name__)

# --- إعدادات البوت ---
TOKEN = os.environ.get("BOT_TOKEN")
if not TOKEN:
    logger.error("Error: TOKEN not found. Please set the BOT_TOKEN environment variable.")
    exit()

BOT_USERNAME = os.environ.get("BOT_USERNAME", "pain1771bot")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")

# وقت بدء تشغيل البوت
start_time = time.time()
# إحصائيات الاستخدام
user_stats = {}
group_stats = {}
# لتخزين من أحال من
referrals = {}
# قائمة المجموعات التي يتواجد فيها البوت
active_groups = set()

# قائمة الكلمات المحظورة
BANNED_WORDS_REGEX = re.compile(
    r"\b(?:احتيال|مخدرات|قمار|رهان|اباحي|بورن|فيديو ساخن|www\.|t\.me|https?://)\b",
    re.IGNORECASE | re.UNICODE
)

# لتحديد معدل الرسائل الخاصة بأمر /start
rate_limits = defaultdict(lambda: {'last_timestamp': 0, 'count': 0})
RATE_LIMIT_DURATION = 60
RATE_LIMIT_THRESHOLD = 5

# --- لوحات الأزرار الثابتة ---
KEYBOARD_MAIN = [
    [InlineKeyboardButton("📄 تفاصيل حسابي", callback_data="details"),
     InlineKeyboardButton("🔗 رابط بروفايلي", callback_data="profile")],
    [InlineKeyboardButton("📈 إحصائيات البوت", callback_data="stats"),
     InlineKeyboardButton("🛠️ أدوات", callback_data="tools")],
    [InlineKeyboardButton("قناة البوت", url="https://t.me/uy_5s")],
    [InlineKeyboardButton("المطور", url="https://t.me/h_77ts")]
]
KEYBOARD_BACK_TO_MAIN = [[InlineKeyboardButton("🔙 عودة للقائمة الرئيسية", callback_data="back_to_main")]]
KEYBOARD_TOOLS = [
    [InlineKeyboardButton("كشف رقم", callback_data="tools_phone"),
     InlineKeyboardButton("بحث عن مستخدم", callback_data="tools_find")],
    [InlineKeyboardButton("مقارنة حسابين", callback_data="tools_compare")],
    [InlineKeyboardButton("معلومات المجموعة", callback_data="tools_groupinfo"),
     InlineKeyboardButton("معلومات الإحالة", callback_data="tools_referral")],
    [InlineKeyboardButton("➕ الكشف في مجموعة", url=f"http://t.me/{BOT_USERNAME}?startgroup=new")],
    [InlineKeyboardButton("🔙 عودة للقائمة الرئيسية", callback_data="back_to_main")]
]
KEYBOARD_PHONE_CONFIRMATION = [
    [InlineKeyboardButton("✅ نعم، متأكد", callback_data="reveal_phone_yes"),
     InlineKeyboardButton("❌ لا، عودة", callback_data="reveal_phone_no")]
]

# --- وظائف مساعدة ---
def get_uptime():
    """حساب وقت تشغيل البوت"""
    uptime_seconds = time.time() - start_time
    minutes, seconds = divmod(uptime_seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{int(hours)}h {int(minutes)}m {int(seconds)}s"

def get_join_date(user_id):
    """تقدير تاريخ انضمام المستخدم باستخدام User ID"""
    try:
        timestamp = 1444108800 + user_id - 180000000
        return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d")
    except Exception:
        return "—"

def update_user_stats(user_id):
    """تحديث إحصائيات المستخدمين"""
    if user_id not in user_stats:
        user_stats[user_id] = 0
    user_stats[user_id] += 1

def update_group_stats(chat_id, command):
    """تحديث إحصائيات المجموعة"""
    if chat_id not in group_stats:
        group_stats[chat_id] = {"whois_count": 0, "find_count": 0, "compare_count": 0}

    if command == "whois":
        group_stats[chat_id]["whois_count"] += 1
    elif command == "find":
        group_stats[chat_id]["find_count"] += 1
    elif command == "compare":
        group_stats[chat_id]["compare_count"] += 1

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """التعامل مع أمر /start"""
    user_id = update.effective_user.id
    update_user_stats(user_id)
    
    context.user_data['start_message_id'] = update.message.message_id

    if context.args:
        referrer_id = context.args[0]
        try:
            referrer_id = int(referrer_id)
            if referrer_id != user_id:
                referrals[user_id] = referrer_id
        except ValueError:
            pass

    text = (
        "👋 أهلًا بك!\n"
        "أنا بوت يعرض معلومات حسابك على تيليجرام. اختر أحد الخيارات أدناه:"
    )
    await update.message.reply_text(
        text, 
        reply_to_message_id=update.message.message_id, 
        reply_markup=InlineKeyboardMarkup(KEYBOARD_MAIN)
    )

def rate_limit_decorator(func):
    """ديكوريتور لتحديد معدل استخدام الأوامر."""
    async def wrapper(update, context):
        user_id = update.effective_user.id
        current_time = time.time()
        
        # تنظيف الإحصائيات القديمة
        if current_time - rate_limits[user_id]['last_timestamp'] > RATE_LIMIT_DURATION:
            rate_limits[user_id]['count'] = 0
            rate_limits[user_id]['last_timestamp'] = current_time
        
        rate_limits[user_id]['count'] += 1
        
        if rate_limits[user_id]['count'] > RATE_LIMIT_THRESHOLD:
            await update.message.reply_text(
                "❌ لقد تجاوزت الحد الأقصى للاستخدام. حاول مرة أخرى لاحقًا.",
                reply_to_message_id=update.message.message_id
            )
            return
        
        return await func(update, context)
    return wrapper

@rate_limit_decorator
async def start_command_rate_limited(update, context):
    await start_command(update, context)

def get_user_info_text(user, chat_member=None):
    """صياغة نص معلومات المستخدم."""
    user_id = user.id
    first_name = user.first_name
    last_name = user.last_name or ""
    username = user.username or "—"
    is_bot = "نعم" if user.is_bot else "لا"
    
    full_name = f"{first_name} {last_name}".strip()
    
    text = (
        f"👤 **تفاصيل الحساب**\n"
        "**━**\n"
        f"  - **الاسم:** `{full_name}`\n"
        f"  - **المعرف (ID):** `{user_id}`\n"
        f"  - **المعرف (Username):** `@{username}`\n"
        f"  - **هل هو بوت:** `{is_bot}`\n"
        f"  - **تاريخ الانضمام:** `{get_join_date(user_id)}`\n"
    )
    return text

async def show_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إظهار تفاصيل الحساب وصورة البروفايل"""
    query = update.callback_query
    user = update.effective_user
    
    text = get_user_info_text(user)
    start_message_id = context.user_data.get('start_message_id')
    
    try:
        await query.message.delete()
    except BadRequest:
        pass

    try:
        photos = await context.bot.get_user_profile_photos(user.id)
        if photos.photos:
            await context.bot.send_photo(
                chat_id=query.message.chat.id,
                photo=photos.photos[0][-1].file_id,
                caption=text,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(KEYBOARD_BACK_TO_MAIN),
                reply_to_message_id=start_message_id
            )
        else:
            await context.bot.send_message(
                chat_id=query.message.chat.id,
                text=text,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(KEYBOARD_BACK_TO_MAIN),
                reply_to_message_id=start_message_id
            )
    except Exception as e:
        logger.error(f"Error fetching profile photo or sending message: {e}")
        await context.bot.send_message(
            chat_id=query.message.chat.id,
            text=text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(KEYBOARD_BACK_TO_MAIN),
            reply_to_message_id=start_message_id
        )

async def show_profile_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إرسال رابط البروفايل أو رسالة خطأ"""
    query = update.callback_query
    user = update.effective_user
    
    if user.username:
        link = f"https://t.me/{user.username}"
        text = f"🔗 رابط بروفايلك:\n{link}"
    else:
        text = (
            "❌ لا يوجد اسم مستخدم لحسابك.\n"
            "لإنشاء رابط، يرجى تعيين اسم مستخدم في إعدادات تيليجرام."
        )
    await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(KEYBOARD_BACK_TO_MAIN))

async def show_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إظهار إحصائيات البوت"""
    query = update.callback_query
    
    if update.effective_chat.type in ['group', 'supergroup']:
        chat_id = update.effective_chat.id
        stats = group_stats.get(chat_id, {"whois_count": 0, "find_count": 0, "compare_count": 0})
        text = (
            "📊 **إحصائيات هذه المجموعة**\n"
            "**━**\n"
            f"• **استخدام `/whois`:** {stats['whois_count']} مرة\n"
            f"• **استخدام `/find`:** {stats['find_count']} مرة\n"
            f"• **استخدام `/compare`:** {stats['compare_count']} مرة\n"
        )
    else:
        text = (
            "📊 **إحصائيات البوت العامة**\n"
            "**━**\n"
            f"• **وقت التشغيل:** {get_uptime()}\n"
            f"• **إجمالي المستخدمين:** {len(user_stats)}\n"
            f"• **عدد التفاعلات:** {sum(user_stats.values())}\n"
            f"• **عدد المجموعات المضاف إليها البوت:** {len(active_groups)}\n"
        )
        
    await query.message.edit_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(KEYBOARD_BACK_TO_MAIN))

async def show_tools(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إظهار قائمة الأدوات"""
    query = update.callback_query
    
    text = (
        "🛠️ **قائمة الأدوات**\n"
        "**━**\n"
        "اختر أحد الأدوات أدناه لمعرفة تفاصيل استخدامها."
    )
    await query.message.edit_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(KEYBOARD_TOOLS))

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """التعامل مع ضغط الأزرار"""
    query = update.callback_query
    await query.answer()
    update_user_stats(query.from_user.id)
    
    if query.data == "details":
        await show_details(update, context)
    elif query.data == "profile":
        await show_profile_link(update, context)
    elif query.data == "stats":
        await show_stats(update, context)
    elif query.data == "tools":
        await show_tools(update, context)
    elif query.data == "back_to_main":
        try:
            await query.message.delete()
        except BadRequest:
            pass
        start_message_id = context.user_data.get('start_message_id')
        text = (
            "👋 أهلًا بك!\n"
            "أنا بوت يعرض معلومات حسابك على تيليجرام. اختر أحد الخيارات أدناه:"
        )
        await context.bot.send_message(
            chat_id=query.message.chat.id,
            text=text,
            reply_markup=InlineKeyboardMarkup(KEYBOARD_MAIN),
            reply_to_message_id=start_message_id
        )

# إعداد Flask routes للـ webhook
@app.route('/')
def index():
    return 'Bot is running!'

@app.route('/health')
def health():
    return 'OK'

def main():
    """تشغيل البوت"""
    application = Application.builder().token(TOKEN).build()

    # إضافة المعالجات
    application.add_handler(CommandHandler("start", start_command_rate_limited))
    application.add_handler(CallbackQueryHandler(button_handler))

    if WEBHOOK_URL:
        # وضع الإنتاج: استخدام Webhook
        port = int(os.environ.get("PORT", 8080))
        
        @app.route(f'/{TOKEN}', methods=['POST'])
        def webhook():
            """استقبال التحديثات من Telegram"""
            try:
                json_str = request.get_data().decode('UTF-8')
                update = Update.de_json(json.loads(json_str), application.bot)
                # استخدام create_task للتعامل مع async
                import asyncio
                asyncio.create_task(application.process_update(update))
                return 'OK'
            except Exception as e:
                logger.error(f"Error processing webhook: {e}")
                return 'ERROR', 500
        
        # تعيين webhook
        async def set_webhook():
            try:
                await application.bot.set_webhook(url=WEBHOOK_URL + TOKEN)
                logger.info(f"Webhook set to: {WEBHOOK_URL + TOKEN}")
            except Exception as e:
                logger.error(f"Error setting webhook: {e}")
        
        # تشغيل إعداد webhook
        import asyncio
        asyncio.run(set_webhook())
        
        # بدء Flask app
        logger.info(f"Starting webhook server on port {port}")
        app.run(host='0.0.0.0', port=port, debug=False)
    else:
        # وضع التطوير: استخدام Polling
        application.run_polling()
        logger.info("Bot started with long polling")

if __name__ == "__main__":
    main()