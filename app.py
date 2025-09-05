# -*- coding: utf-8 -*-
import os
import time
import re
import json
import logging
from datetime import datetime
from collections import defaultdict
from flask import Flask, request
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters
from telegram.error import BadRequest
from telegram.constants import ParseMode

# إعداد التسجيل
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- إعدادات البوت ---
TOKEN = os.environ.get("BOT_TOKEN")
if not TOKEN:
    logger.error("Error: TOKEN not found. Please set the BOT_TOKEN environment variable.")
    exit()

BOT_USERNAME = os.environ.get("BOT_USERNAME", "pain1771bot")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")

# وقت بدء تشغيل البوت
start_time = time.time()
user_stats = {}
group_stats = {}
referrals = {}
active_groups = set()

# --- لوحات الأزرار الثابتة ---
KEYBOARD_MAIN = [
    [InlineKeyboardButton("📄 تفاصيل حسابي", callback_data="details"),
     InlineKeyboardButton("🔗 رابط بروفايلي", callback_data="profile")],
    [InlineKeyboardButton("📈 إحصائيات البوت", callback_data="stats")],
    [InlineKeyboardButton("قناة البوت", url="https://t.me/uy_5s")],
    [InlineKeyboardButton("المطور", url="https://t.me/h_77ts")]
]
KEYBOARD_BACK_TO_MAIN = [[InlineKeyboardButton("🔙 عودة للقائمة الرئيسية", callback_data="back_to_main")]]

def get_uptime():
    uptime_seconds = time.time() - start_time
    minutes, seconds = divmod(uptime_seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{int(hours)}h {int(minutes)}m {int(seconds)}s"

def get_join_date(user_id):
    try:
        timestamp = 1444108800 + user_id - 180000000
        return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d")
    except Exception:
        return "—"

def update_user_stats(user_id):
    if user_id not in user_stats:
        user_stats[user_id] = 0
    user_stats[user_id] += 1

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    update_user_stats(user_id)
    
    text = (
        "👋 أهلًا بك!\n"
        "أنا بوت يعرض معلومات حسابك على تيليجرام. اختر أحد الخيارات أدناه:"
    )
    await update.message.reply_text(
        text, 
        reply_to_message_id=update.message.message_id, 
        reply_markup=InlineKeyboardMarkup(KEYBOARD_MAIN)
    )

def get_user_info_text(user):
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
    query = update.callback_query
    user = update.effective_user
    text = get_user_info_text(user)
    
    try:
        photos = await context.bot.get_user_profile_photos(user.id)
        if photos.photos:
            await query.message.reply_photo(
                photos.photos[0][-1].file_id, 
                caption=text, 
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(KEYBOARD_BACK_TO_MAIN)
            )
        else:
            await query.message.reply_text(
                text, 
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(KEYBOARD_BACK_TO_MAIN)
            )
    except Exception as e:
        logger.error(f"Error: {e}")
        await query.message.reply_text(
            text, 
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(KEYBOARD_BACK_TO_MAIN)
        )

async def show_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    text = (
        "📊 **إحصائيات البوت العامة**\n"
        "**━**\n"
        f"• **وقت التشغيل:** {get_uptime()}\n"
        f"• **إجمالي المستخدمين:** {len(user_stats)}\n"
        f"• **عدد التفاعلات:** {sum(user_stats.values())}\n"
    )
    await query.message.edit_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(KEYBOARD_BACK_TO_MAIN))

async def show_profile_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    update_user_stats(query.from_user.id)
    
    if query.data == "details":
        await show_details(update, context)
    elif query.data == "profile":
        await show_profile_link(update, context)
    elif query.data == "stats":
        await show_stats(update, context)
    elif query.data == "back_to_main":
        text = (
            "👋 أهلًا بك!\n"
            "أنا بوت يعرض معلومات حسابك على تيليجرام. اختر أحد الخيارات أدناه:"
        )
        await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(KEYBOARD_MAIN))

# إنشاء Flask app
app = Flask(__name__)

@app.route('/')
def index():
    return 'Bot is running!'

@app.route('/health')
def health():
    return 'OK'

# إعداد البوت للـ webhook
if WEBHOOK_URL:
    application = Application.builder().token(TOKEN).build()
    
    # إضافة المعالجات
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CallbackQueryHandler(button_handler))

    @app.route(f'/{TOKEN}', methods=['POST'])
    def webhook():
        try:
            json_str = request.get_data().decode('UTF-8')
            update_dict = json.loads(json_str)
            update = Update.de_json(update_dict, application.bot)
            
            # استخدام asyncio للتعامل مع async functions
            import asyncio
            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
            
            loop.run_until_complete(application.process_update(update))
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
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    
    loop.run_until_complete(set_webhook())

# للتشغيل المحلي
if __name__ == "__main__":
    if WEBHOOK_URL:
        port = int(os.environ.get("PORT", 8080))
        app.run(host='0.0.0.0', port=port, debug=False)
    else:
        # للتطوير المحلي
        import asyncio
        async def main():
            application = Application.builder().token(TOKEN).build()
            application.add_handler(CommandHandler("start", start_command))
            application.add_handler(CallbackQueryHandler(button_handler))
            
            await application.initialize()
            await application.start()
            await application.updater.start_polling()
            
            # إبقاء البوت يعمل
            import signal
            stop_signals = (signal.SIGTERM, signal.SIGINT)
            for sig in stop_signals:
                signal.signal(sig, lambda s, f: application.stop())
            
            await application.updater.idle()

        asyncio.run(main())