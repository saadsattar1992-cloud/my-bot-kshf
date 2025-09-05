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
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler, MessageHandler, CallbackContext, ChatMemberHandler
from telegram.ext.filters import Filters
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

def start_command(update: Update, context: CallbackContext):
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
    update.message.reply_text(
        text, 
        reply_to_message_id=update.message.message_id, 
        reply_markup=InlineKeyboardMarkup(KEYBOARD_MAIN)
    )

def rate_limit_decorator(func):
    """ديكوريتور لتحديد معدل استخدام الأوامر."""
    def wrapper(update, context):
        user_id = update.effective_user.id
        current_time = time.time()
        
        # تنظيف الإحصائيات القديمة
        if current_time - rate_limits[user_id]['last_timestamp'] > RATE_LIMIT_DURATION:
            rate_limits[user_id]['count'] = 0
            rate_limits[user_id]['last_timestamp'] = current_time
        
        rate_limits[user_id]['count'] += 1
        
        if rate_limits[user_id]['count'] > RATE_LIMIT_THRESHOLD:
            update.message.reply_text(
                "❌ لقد تجاوزت الحد الأقصى للاستخدام. حاول مرة أخرى لاحقًا.",
                reply_to_message_id=update.message.message_id
            )
            return
        
        return func(update, context)
    return wrapper

@rate_limit_decorator
def start_command_rate_limited(update, context):
    start_command(update, context)

def show_main_menu(update: Update, context: CallbackContext, query=None):
    """يعرض القائمة الرئيسية. يمكن استخدامه من CallbackQuery أو مباشرة من دالة أخرى."""
    text = (
        "👋 أهلًا بك!\n"
        "أنا بوت يعرض معلومات حسابك على تيليجرام. اختر أحد الخيارات أدناه:"
    )
    if query:
        try:
            query.message.delete()
        except BadRequest:
            pass
        
        context.bot.send_message(
            chat_id=query.message.chat.id,
            text=text,
            reply_markup=InlineKeyboardMarkup(KEYBOARD_MAIN)
        )
    else:
        update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(KEYBOARD_MAIN))

def show_details(update: Update, context: CallbackContext):
    """إظهار تفاصيل الحساب وصورة البروفايل"""
    query = update.callback_query
    user = update.effective_user
    
    text = get_user_info_text(user)
    start_message_id = context.user_data.get('start_message_id')
    
    try:
        query.message.delete()
    except BadRequest:
        pass

    try:
        photos = context.bot.get_user_profile_photos(user.id).photos
        if photos:
            context.bot.send_photo(
                chat_id=query.message.chat.id,
                photo=photos[0][-1].file_id,
                caption=text,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(KEYBOARD_BACK_TO_MAIN),
                reply_to_message_id=start_message_id
            )
        else:
            context.bot.send_message(
                chat_id=query.message.chat.id,
                text=text,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(KEYBOARD_BACK_TO_MAIN),
                reply_to_message_id=start_message_id
            )
    except Exception as e:
        logger.error(f"Error fetching profile photo or sending message: {e}")
        context.bot.send_message(
            chat_id=query.message.chat.id,
            text=text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(KEYBOARD_BACK_TO_MAIN),
            reply_to_message_id=start_message_id
        )

def show_profile_link(update: Update, context: CallbackContext):
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
    query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(KEYBOARD_BACK_TO_MAIN))

def show_stats(update: Update, context: CallbackContext):
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
            f"• **أكثر المجموعات استخدامًا للأدوات:** {max(group_stats, key=lambda k: sum(group_stats[k].values())) if group_stats else '—'}\n"
        )
        
    query.message.edit_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(KEYBOARD_BACK_TO_MAIN))

def show_tools(update: Update, context: CallbackContext):
    """إظهار قائمة الأدوات"""
    query = update.callback_query
    
    text = (
        "🛠️ **قائمة الأدوات**\n"
        "**━**\n"
        "اختر أحد الأدوات أدناه لمعرفة تفاصيل استخدامها."
    )
    query.message.edit_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(KEYBOARD_TOOLS))

def show_tool_details(update: Update, context: CallbackContext):
    """إظهار تفاصيل كل أداة على حدة"""
    query = update.callback_query
    command = query.data.split('_')[1]
    text = ""
    
    if command == "phone":
        pass
    elif command == "find":
        text = (
            "**`بحث عن مستخدم` (`/find`)**\n"
            "**━**\n"
            "▫️ **الوظيفة:** الحصول على معلومات أي مستخدم لديه اسم مستخدم.\n"
            "▫️ **مثال:** `/find @username`\n"
            "▫️ **المكان:** يعمل في الخاص والمجموعات.\n"
        )
    elif command == "compare":
        text = (
            "**`مقارنة حسابين` (`/compare`)**\n"
            "**━**\n"
            "▫️ **الوظيفة:** لمقارنة معلومات حسابين معًا.\n"
            "▫️ **مثال:** `/compare @user1 @user2`\n"
            "▫️ **المكان:** يعمل في الخاص والمجموعات.\n"
        )
    elif command == "groupinfo":
        text = (
            "**`معلومات المجموعة`**\n"
            "**━**\n"
            "▫️ **الوظيفة:** الحصول على اسم ومعرف (ID) المجموعة أو القناة.\n"
            "▫️ **كيفية الاستخدام:** اضغط على زر 'معلومات المجموعة' في أي دردشة جماعية.\n"
            "▫️ **المكان:** يعمل في المجموعات والقنوات فقط.\n"
        )
    elif command == "referral":
        text = (
            "**`معلومات الإحالة`**\n"
            "**━**\n"
            "▫️ **الوظيفة:** لمعرفة من قام بإحالتك (دعوتك) إلى البوت.\n"
            "▫️ **كيفية الاستخدام:** اضغط على الزر ليقوم البوت بالبحث عن من قام بدعوتك.\n"
            "▫️ **المكان:** يعمل في الخاص فقط.\n"
        )
    
    query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(KEYBOARD_BACK_TO_MAIN), parse_mode=ParseMode.MARKDOWN)
    
def handle_whois_request(update: Update, context: CallbackContext):
    """يعالج رسالة المستخدم للكشف عن المعلومات بناءً على الرد أو الكاتب"""
    message = update.message
    text = message.text.lower().strip()
    
    keywords = ['كشف', 'عرض', 'كشف معلومات', 'معلوماتي', 'معلوماته', 'انشائي', 'عرض معلوماتي', 'ايدي', 'id', 'حسابي', 'تفاصيل حسابي']
    
    if message.chat.type in ['group', 'supergroup']:
        if any(keyword in text for keyword in keywords):
            if message.reply_to_message:
                user_to_check = message.reply_to_message.from_user
            else:
                user_to_check = message.from_user
            send_whois_info(update, context, user_to_check)

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

def send_whois_info(update: Update, context: CallbackContext, user):
    """يرسل معلومات المستخدم مع الصورة ككابشن"""
    if update.effective_chat.type in ['group', 'supergroup']:
        update_group_stats(update.effective_chat.id, "whois")

    try:
        chat_member = context.bot.get_chat_member(chat_id=update.effective_chat.id, user_id=user.id)
        text = get_user_info_text(user, chat_member)
    except Exception:
        text = get_user_info_text(user)
    
    try:
        photos = context.bot.get_user_profile_photos(user.id).photos
        if photos:
            update.message.reply_photo(photos[0][-1].file_id, caption=text, parse_mode=ParseMode.MARKDOWN, reply_to_message_id=update.message.message_id)
        else:
            update.message.reply_markdown(text, reply_to_message_id=update.message.message_id)
    except Exception:
        update.message.reply_markdown(text, reply_to_message_id=update.message.message_id)

@rate_limit_decorator
def find_user_command(update: Update, context: CallbackContext):
    """البحث عن مستخدم باستخدام اسمه المستعار"""
    message = update.message
    
    if message.chat.type in ['group', 'supergroup']:
        update_group_stats(message.chat.id, "find")

    if not context.args:
        message.reply_text("❌ يرجى استخدام الأمر بالشكل التالي: `/find @username`", reply_to_message_id=message.message_id)
        return

    username = context.args[0].replace('@', '')
    try:
        user = context.bot.get_chat(f"@{username}")
        if user:
            send_whois_info(update, context, user)
    except Exception:
        message.reply_text("❌ لم يتم العثور على المستخدم أو لا يمكنني الوصول إلى معلوماته.", reply_to_message_id=message.message_id)

@rate_limit_decorator
def compare_users_command(update: Update, context: CallbackContext):
    """مقارنة معلومات مستخدمين"""
    message = update.message
    
    if message.chat.type in ['group', 'supergroup']:
        update_group_stats(message.chat.id, "compare")
    
    if len(context.args) != 2:
        message.reply_text("❌ يرجى استخدام الأمر بالشكل التالي: `/compare @user1 @user2`", reply_to_message_id=message.message_id)
        return

    username1 = context.args[0].replace('@', '')
    username2 = context.args[1].replace('@', '')
    
    try:
        user1 = context.bot.get_chat(f"@{username1}")
        user2 = context.bot.get_chat(f"@{username2}")
        
        text = "**📊 مقارنة المستخدمين**\n\n"
        text += f"**👤 المستخدم الأول: @{user1.username}**\n"
        text += get_user_info_text(user1).replace("👤 تفاصيل الحساب\n**━**\n", "")
        text += "\n"
        text += f"**👤 المستخدم الثاني: @{user2.username}**\n"
        text += get_user_info_text(user2).replace("👤 تفاصيل الحساب\n**━**\n", "")

        message.reply_markdown(text, reply_to_message_id=message.message_id)
        
    except Exception as e:
        logger.error(f"Error in compare: {e}")
        message.reply_text("❌ حدث خطأ في الحصول على معلومات أحد المستخدمين.", reply_to_message_id=message.message_id)

def show_group_info(update: Update, context: CallbackContext):
    """إظهار معلومات المجموعة (الدردشة)"""
    query = update.callback_query
    chat = update.effective_chat
    
    text = (
        "**ℹ️ معلومات المجموعة/القناة**\n"
        "**━**\n"
        f"  - **اسم المجموعة:** `{chat.title}`\n"
        f"  - **المعرف (ID):** `{chat.id}`\n"
        f"  - **المعرّف (Username):** `@{chat.username if chat.username else '—'}`\n"
        f"  - **نوع الدردشة:** {'خاصة' if chat.type == 'private' else 'مجموعة' if chat.type == 'group' else 'مجموعة خارقة' if chat.type == 'supergroup' else 'قناة'}\n"
    )
    query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(KEYBOARD_BACK_TO_MAIN), parse_mode=ParseMode.MARKDOWN)

def show_bot_info(update: Update, context: CallbackContext):
    """إظهار معلومات البوت"""
    query = update.callback_query
    bot_user = context.bot.get_me()
    text = (
        "**🤖 معلومات البوت**\n"
        "**━**\n"
        f"  - **الاسم:** `{bot_user.first_name}`\n"
        f"  - **المعرّف (ID):** `{bot_user.id}`\n"
        f"  - **المعرّف (Username):** `@{bot_user.username}`\n"
    )
    query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(KEYBOARD_BACK_TO_MAIN), parse_mode=ParseMode.MARKDOWN)

def show_referral_info(update: Update, context: CallbackContext):
    """إظهار معلومات الإحالة"""
    query = update.callback_query
    user_id = query.from_user.id
    referrer_id = referrals.get(user_id)
    if referrer_id:
        try:
            referrer_user = context.bot.get_chat(referrer_id)
            referrer_name = referrer_user.first_name
            referrer_username = referrer_user.username
            text = (
                "**🔗 معلومات الإحالة**\n"
                "**━**\n"
                f"  - **أحالتك:** `{referrer_name} (@{referrer_username})`\n"
                f"  - **معرف المحيل (ID):** `{referrer_id}`\n"
            )
        except Exception:
            text = (
                "**🔗 معلومات الإحالة**\n"
                "**━**\n"
                f"  - **أحالتك:** لم يتمكن البوت من الحصول على معلومات المحيل.\n"
                f"  - **معرف المحيل (ID):** `{referrer_id}`\n"
            )
    else:
        text = "❌ لم يتم إحالتك بواسطة أحد."
    query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(KEYBOARD_BACK_TO_MAIN), parse_mode=ParseMode.MARKDOWN)

def confirm_phone_reveal(update: Update, context: CallbackContext):
    """يطلب من المستخدم التأكيد على كشف الرقم"""
    query = update.callback_query
    query.message.edit_text(
        "📞 **كشف رقمك**\n"
        "**━**\n"
        "هل أنت متأكد من أنك تريد الكشف عن رقم هاتفك؟",
        reply_markup=InlineKeyboardMarkup(KEYBOARD_PHONE_CONFIRMATION)
    )

def reveal_phone_number(update: Update, context: CallbackContext):
    """يطلب من المستخدم مشاركة جهة الاتصال بعد التأكيد"""
    query = update.callback_query
    keyboard = [[telegram.KeyboardButton("مشاركة جهة الاتصال", request_contact=True)]]
    reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
    
    try:
        query.message.delete()
    except BadRequest:
        pass
    
    context.bot.send_message(
        chat_id=query.message.chat.id,
        text="اضغط على الزر أدناه لمشاركة جهة الاتصال الخاصة بك:",
        reply_markup=reply_markup
    )

def handle_contact_share(update: Update, context: CallbackContext):
    """التعامل مع مشاركة رقم الهاتف"""
    message = update.message
    contact = message.contact
    phone_number = contact.phone_number
    
    # يجب إزالة لوحة المفاتيح بعد الاستخدام
    context.bot.send_message(
        chat_id=message.chat.id,
        text="شكرًا لمشاركة رقمك.",
        reply_markup=ReplyKeyboardRemove()
    )
    
    text = (
        f"📱 **رقم هاتفك**\n"
        f"**━**\n"
        f"  - **الرقم:** `{phone_number}`"
    )
    
    start_message_id = context.user_data.get('start_message_id')
    
    context.bot.send_message(
        chat_id=message.chat.id,
        text=text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(KEYBOARD_BACK_TO_MAIN),
        reply_to_message_id=start_message_id
    )

def handle_suspicious_content(update: Update, context: CallbackContext):
    """حذف الصور والفيديوهات في الخاص"""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    message_id = update.message.message_id
    
    if update.effective_chat.type == 'private':
        try:
            context.bot.delete_message(chat_id=chat_id, message_id=message_id)
        except BadRequest as e:
            logger.error(f"Error deleting message: {e}")

def handle_banned_words(update: Update, context: CallbackContext):
    """حذف الرسائل التي تحتوي على كلمات محظورة."""
    message = update.effective_message
    if not message or not message.text:
        return
        
    if BANNED_WORDS_REGEX.search(message.text):
        try:
            message.delete()
            logger.info(f"Deleted message containing a banned word from user {message.from_user.id}")
        except BadRequest as e:
            logger.error(f"Could not delete message: {e}")
                
def group_commands_command(update: Update, context: CallbackContext):
    """يعرض أوامر البوت المخصصة للمجموعات"""
    if update.effective_chat.type not in ['group', 'supergroup']:
        update.message.reply_text("هذا الأمر مخصص للمجموعات فقط.", reply_to_message_id=update.message.message_id)
        return

    text = (
        "📜 **أوامر البوت في المجموعات**\n"
        "**━**\n"
        "• `/whois` أو `كشف` (بالرد على رسالة): لمعرفة معلومات المستخدم.\n"
        "• `/find @username`: للبحث عن مستخدم باستخدام اسمه.\n"
        "• `/compare @user1 @user2`: لمقارنة معلومات حسابين.\n"
        "• `/groupinfo`: لمعرفة معلومات المجموعة.\n"
        "• `/botinfo`: لمعرفة معلومات البوت.\n"
        "• `/groupcommands` أو `اوامر`: لعرض هذه القائمة."
    )
    update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_to_message_id=update.message.message_id)

def button_handler(update: Update, context: CallbackContext):
    """التعامل مع ضغط الأزرار"""
    query = update.callback_query
    query.answer()
    update_user_stats(query.from_user.id)
    
    if query.data == "details":
        show_details(update, context)
    elif query.data == "profile":
        show_profile_link(update, context)
    elif query.data == "stats":
        show_stats(update, context)
    elif query.data == "tools":
        show_tools(update, context)
    elif query.data.startswith("tools_"):
        if query.data == "tools_phone":
            confirm_phone_reveal(update, context)
        elif query.data == "tools_referral":
            show_referral_info(update, context)
        elif query.data == "tools_groupinfo":
            show_group_info(update, context)
        else:
            show_tool_details(update, context)
    elif query.data == "reveal_phone_yes":
        reveal_phone_number(update, context)
    elif query.data == "reveal_phone_no":
        show_tools(update, context)
    elif query.data == "back_to_main":
        try:
            query.message.delete()
        except BadRequest:
            pass
        start_message_id = context.user_data.get('start_message_id')
        text = (
            "👋 أهلًا بك!\n"
            "أنا بوت يعرض معلومات حسابك على تيليجرام. اختر أحد الخيارات أدناه:"
        )
        context.bot.send_message(
            chat_id=query.message.chat.id,
            text=text,
            reply_markup=InlineKeyboardMarkup(KEYBOARD_MAIN),
            reply_to_message_id=start_message_id
        )

def manage_group_membership(update: Update, context: CallbackContext):
    """إدارة قائمة المجموعات التي يتواجد فيها البوت."""
    chat_id = update.effective_chat.id
    status = update.my_chat_member.new_chat_member.status
    
    if status == 'member':
        active_groups.add(chat_id)
    elif status == 'left' or status == 'kicked':
        if chat_id in active_groups:
            active_groups.remove(chat_id)

# إعداد Flask routes للـ webhook
@app.route('/')
def index():
    return 'Bot is running!'

@app.route('/health')
def health():
    return 'OK'

def main():
    """تشغيل البوت"""
    updater = Updater(TOKEN)
    dp = updater.dispatcher

    # إضافة المعالجات
    dp.add_handler(CommandHandler("start", start_command_rate_limited))
    dp.add_handler(CommandHandler("whois", lambda update, context: send_whois_info(update, context, update.effective_user)))
    dp.add_handler(CommandHandler("find", find_user_command))
    dp.add_handler(CommandHandler("compare", compare_users_command))
    dp.add_handler(CommandHandler("groupcommands", group_commands_command))
    dp.add_handler(CommandHandler("groupinfo", lambda update, context: show_group_info(update, context) if hasattr(update, 'callback_query') else None))
    dp.add_handler(CommandHandler("botinfo", lambda update, context: show_bot_info(update, context) if hasattr(update, 'callback_query') else None))
    dp.add_handler(CallbackQueryHandler(button_handler))
    dp.add_handler(MessageHandler(Filters.contact, handle_contact_share))
    dp.add_handler(MessageHandler(Filters.private & (Filters.photo | Filters.video), handle_suspicious_content))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_banned_words))
    dp.add_handler(MessageHandler(Filters.regex(r'^(اوامر|الاوامر)$') & Filters.chat_type.groups, group_commands_command))
    
    # دمج معالجات الكلمات في معالج واحد
    keywords_regex = re.compile(r'^(كشف|عرض|كشف معلومات|معلوماتي|معلوماته|انشائي|عرض معلوماتي|ايدي|id|حسابي|تفاصيل حسابي)$', re.IGNORECASE | re.UNICODE)
    dp.add_handler(MessageHandler(Filters.text & Filters.regex(keywords_regex) & Filters.chat_type.groups, handle_whois_request))

    dp.add_handler(ChatMemberHandler(manage_group_membership))

    if WEBHOOK_URL:
        # وضع الإنتاج: استخدام Webhook
        port = int(os.environ.get("PORT", 8080))
        
        @app.route(f'/{TOKEN}', methods=['POST'])
        def webhook():
            """استقبال التحديثات من Telegram"""
            try:
                json_str = request.get_data().decode('UTF-8')
                update = Update.de_json(json.loads(json_str), updater.bot)
                dp.process_update(update)
                return 'OK'
            except Exception as e:
                logger.error(f"Error processing webhook: {e}")
                return 'ERROR', 500
        
        # تعيين webhook
        try:
            updater.bot.set_webhook(url=WEBHOOK_URL + TOKEN)
            logger.info(f"Webhook set to: {WEBHOOK_URL + TOKEN}")
        except Exception as e:
            logger.error(f"Error setting webhook: {e}")
        
        # بدء Flask app
        logger.info(f"Starting webhook server on port {port}")
        app.run(host='0.0.0.0', port=port, debug=False)
    else:
        # وضع التطوير: استخدام Polling
        updater.start_polling()
        logger.info("Bot started with long polling")
        updater.idle()

if __name__ == "__main__":
    main()