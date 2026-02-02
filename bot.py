import telebot
from telebot import types
import qrcode
import time
import threading
from datetime import datetime, timedelta
import logging
from io import BytesIO
import json
import os
import sys

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# ============ CONFIG FROM ENVIRONMENT ============
# Railway pe Environment Variables se values aayengi
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
ADMIN_ID = os.environ.get("ADMIN_ID", "")
LOG_CHANNEL = os.environ.get("LOG_CHANNEL", "")
SUPPORT_USERNAME = os.environ.get("SUPPORT_USERNAME", "")
DEMO_CHANNEL_LINK = os.environ.get("DEMO_CHANNEL_LINK", "")
UPI_ID = os.environ.get("UPI_ID", "")
UPI_NAME = os.environ.get("UPI_NAME", "Membership")
AMOUNT = os.environ.get("AMOUNT", "99")

# Spam protection settings
MAX_SPAM_COUNT = int(os.environ.get("MAX_SPAM_COUNT", "5"))
SPAM_TIME_WINDOW = int(os.environ.get("SPAM_TIME_WINDOW", "10"))
WARNING_MESSAGES = ["⚠️ Please don't spam!", "⚠️ This is your last warning!", "⛔ You are being blocked for spamming!"]
BLOCK_DURATIONS = [300, 900, 1800]  # 5min, 15min, 30min (seconds)

# Data storage files - Railway persistent volume use karega
DATA_DIR = "/data"  # Railway volume mount point
START_MESSAGE_FILE = os.path.join(DATA_DIR, "start_message.json")
USERS_DATA_FILE = os.path.join(DATA_DIR, "users_data.json")
SPAM_DATA_FILE = os.path.join(DATA_DIR, "spam_data.json")

# Ensure data directory exists
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR, exist_ok=True)
    print(f"✅ Created data directory: {DATA_DIR}")

# ===============================
bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")

# Initialize data storage
start_message_data = {}
users_data = {}
spam_data = {}  # {user_id: {"requests": [timestamps], "warnings": int, "blocked_until": timestamp, "block_level": int, "ban_reason": str, "banned_by": int}}

# ============ DATA MANAGEMENT FUNCTIONS ============
def load_data():
    """Load data from Railway persistent volume"""
    global start_message_data, users_data, spam_data
    print("📂 Loading data from persistent storage...")
    
    try:
        # Load start message
        if os.path.exists(START_MESSAGE_FILE):
            with open(START_MESSAGE_FILE, 'r') as f:
                start_message_data = json.load(f)
            print(f"✅ Loaded start message data")
        else:
            print("⚠️ No start message data found")
            start_message_data = {}
    except Exception as e:
        print(f"❌ Error loading start message: {e}")
        start_message_data = {}
    
    try:
        # Load users data
        if os.path.exists(USERS_DATA_FILE):
            with open(USERS_DATA_FILE, 'r') as f:
                users_data = json.load(f)
            print(f"✅ Loaded {len(users_data)} users from {USERS_DATA_FILE}")
        else:
            print("⚠️ No users data found, starting fresh")
            users_data = {}
    except Exception as e:
        print(f"❌ Error loading users data: {e}")
        users_data = {}
    
    try:
        # Load spam data
        if os.path.exists(SPAM_DATA_FILE):
            with open(SPAM_DATA_FILE, 'r') as f:
                spam_data = json.load(f)
            print(f"✅ Loaded spam data for {len(spam_data)} users")
        else:
            print("⚠️ No spam data found")
            spam_data = {}
    except Exception as e:
        print(f"❌ Error loading spam data: {e}")
        spam_data = {}
    
    print(f"📊 Total users in memory: {len(users_data)}")

def save_start_message():
    """Save start message to Railway persistent volume"""
    try:
        with open(START_MESSAGE_FILE, 'w') as f:
            json.dump(start_message_data, f, indent=4)
        print("💾 Start message saved")
    except Exception as e:
        logging.error(f"Error saving start message: {e}")

def save_users_data():
    """Save users data to Railway persistent volume"""
    try:
        with open(USERS_DATA_FILE, 'w') as f:
            json.dump(users_data, f, indent=4)
        print(f"💾 Users data saved ({len(users_data)} users)")
    except Exception as e:
        logging.error(f"Error saving users data: {e}")

def save_spam_data():
    """Save spam data to Railway persistent volume"""
    try:
        with open(SPAM_DATA_FILE, 'w') as f:
            json.dump(spam_data, f, indent=4)
    except Exception as e:
        logging.error(f"Error saving spam data: {e}")

def save_all_data():
    """Save all data at once"""
    save_start_message()
    save_users_data()
    save_spam_data()
    print("💾 All data saved successfully")

# Load data on startup
load_data()

# ============ SPAM PROTECTION FUNCTIONS ============
def update_user_activity(user_id):
    """Update user activity timestamp"""
    user_id_str = str(user_id)
    current_time = time.time()
    
    if user_id_str not in spam_data:
        spam_data[user_id_str] = {
            "requests": [],
            "warnings": 0,
            "blocked_until": 0,
            "block_level": 0,
            "ban_reason": "",
            "banned_by": 0
        }
    
    # Ensure requests key exists
    if "requests" not in spam_data[user_id_str]:
        spam_data[user_id_str]["requests"] = []
    
    # Clean old requests (older than SPAM_TIME_WINDOW)
    spam_data[user_id_str]["requests"] = [
        ts for ts in spam_data[user_id_str]["requests"] 
        if current_time - ts < SPAM_TIME_WINDOW
    ]
    
    # Add new request
    spam_data[user_id_str]["requests"].append(current_time)
    
    # Auto-save every 50 updates
    if len(spam_data) % 50 == 0:
        save_spam_data()
    
    return len(spam_data[user_id_str]["requests"])

def check_user_blocked(user_id):
    """Check if user is currently blocked"""
    user_id_str = str(user_id)
    
    if user_id_str not in spam_data:
        return False, None
    
    user_data = spam_data[user_id_str]
    
    # Ensure blocked_until key exists
    if "blocked_until" not in user_data:
        user_data["blocked_until"] = 0
    
    current_time = time.time()
    
    if user_data["blocked_until"] > current_time:
        time_left = int(user_data["blocked_until"] - current_time)
        minutes = time_left // 60
        seconds = time_left % 60
        hours = minutes // 60
        minutes = minutes % 60
        
        warning_msg = f"⛔ <b>YOU ARE BLOCKED!</b>\n\n"
        
        # Check if admin ban or spam ban
        if user_data.get("ban_reason"):
            warning_msg += f"<b>Reason:</b> {user_data['ban_reason']}\n"
        
        if hours > 0:
            warning_msg += f"⏳ Please wait <b>{hours} hours {minutes} minutes</b> before using the bot again.\n\n"
        else:
            warning_msg += f"⏳ Please wait <b>{minutes}:{seconds:02d}</b> minutes before using the bot again.\n\n"
        
        warning_msg += f"<b>Warning:</b> Further violations will increase block duration!"
        
        return True, warning_msg
    
    return False, None

def check_spam(user_id):
    """Check if user is spamming and take action"""
    user_id_str = str(user_id)
    
    # First check if blocked
    is_blocked, block_msg = check_user_blocked(user_id)
    if is_blocked:
        return block_msg
    
    current_time = time.time()
    
    # Update activity and get request count
    request_count = update_user_activity(user_id)
    
    # Ensure all keys exist
    if "warnings" not in spam_data[user_id_str]:
        spam_data[user_id_str]["warnings"] = 0
    if "block_level" not in spam_data[user_id_str]:
        spam_data[user_id_str]["block_level"] = 0
    if "blocked_until" not in spam_data[user_id_str]:
        spam_data[user_id_str]["blocked_until"] = 0
    
    # Check if spamming
    if request_count >= MAX_SPAM_COUNT:
        # Block the user
        user_data = spam_data[user_id_str]
        user_data["block_level"] = min(2, user_data.get("block_level", 0) + 1)
        block_duration = BLOCK_DURATIONS[user_data["block_level"]]
        user_data["blocked_until"] = current_time + block_duration
        user_data["requests"] = []  # Reset requests after blocking
        user_data["warnings"] = 0
        
        # Notify admin
        try:
            admin_msg = f"""
🚨 <b>USER BLOCKED FOR SPAM</b>

👤 User ID: <code>{user_id}</code>
📛 Block Level: {user_data['block_level'] + 1}
⏰ Duration: {block_duration//60} minutes
🔢 Spam Count: {request_count}
            """
            bot.send_message(ADMIN_ID, admin_msg, parse_mode="HTML")
        except:
            pass
        
        save_spam_data()
        
        time_left = block_duration
        minutes = time_left // 60
        seconds = time_left % 60
        
        block_message = f"⛔ <b>YOU ARE BLOCKED FOR SPAMMING!</b>\n\n"
        block_message += f"⏳ Please wait <b>{minutes}:{seconds:02d}</b> minutes before using the bot again.\n\n"
        block_message += f"<b>Warning:</b> Next spam will increase block duration!"
        
        return block_message
    
    # Send warning if close to limit
    if request_count >= 3:
        warning_level = min(2, request_count - 3)
        if spam_data[user_id_str].get("warnings", 0) < warning_level + 1:
            spam_data[user_id_str]["warnings"] = warning_level + 1
            save_spam_data()
            
            warning_msg = f"{WARNING_MESSAGES[warning_level]}\n\n"
            warning_msg += f"⚠️ <b>You have {MAX_SPAM_COUNT - request_count} attempts left before being blocked!</b>"
            
            # Send warning as separate message
            try:
                bot.send_message(user_id, warning_msg, parse_mode="HTML")
            except:
                pass
            
            # Return None so main function continues
            return None
    
    return None

def reset_spam_counter(user_id):
    """Reset spam counter for legitimate users"""
    user_id_str = str(user_id)
    
    if user_id_str in spam_data:
        # Only reset if not blocked
        if spam_data[user_id_str].get("blocked_until", 0) < time.time():
            spam_data[user_id_str]["requests"] = []
            spam_data[user_id_str]["warnings"] = 0

def ban_user(user_id, duration_seconds, reason="", banned_by=ADMIN_ID):
    """Ban a user manually"""
    user_id_str = str(user_id)
    current_time = time.time()
    
    if user_id_str not in spam_data:
        spam_data[user_id_str] = {
            "requests": [],
            "warnings": 0,
            "blocked_until": 0,
            "block_level": 0,
            "ban_reason": reason,
            "banned_by": banned_by
        }
    
    spam_data[user_id_str]["blocked_until"] = current_time + duration_seconds
    spam_data[user_id_str]["ban_reason"] = reason
    spam_data[user_id_str]["banned_by"] = banned_by
    spam_data[user_id_str]["block_level"] = 3  # Mark as admin ban
    
    save_spam_data()
    
    # Try to notify the user
    try:
        if duration_seconds >= 3600:
            time_display = f"{int(duration_seconds/3600)} hours"
        elif duration_seconds >= 60:
            time_display = f"{int(duration_seconds/60)} minutes"
        else:
            time_display = f"{duration_seconds} seconds"
        
        notice_msg = f"""
⛔ <b>BOT ACCESS BLOCKED</b>

📛 <b>You have been banned from using this bot!</b>

⏰ <b>Duration:</b> {time_display}
📝 <b>Reason:</b> {reason if reason else "Violation of bot rules"}

⚠️ <b>Your access will be restored after the specified time.</b>
        """
        
        bot.send_message(user_id, notice_msg, parse_mode="HTML")
    except:
        pass
    
    return True

# Initialize spam_data for all existing users on startup
def initialize_spam_data():
    """Ensure all existing users have spam_data entries"""
    print("🔄 Initializing spam data for existing users...")
    initialized = 0
    for user_id_str in users_data.keys():
        if user_id_str not in spam_data:
            spam_data[user_id_str] = {
                "requests": [],
                "warnings": 0,
                "blocked_until": 0,
                "block_level": 0,
                "ban_reason": "",
                "banned_by": 0
            }
            initialized += 1
    
    if initialized > 0:
        save_spam_data()
        print(f"✅ Initialized spam data for {initialized} users")

# Initialize spam data on startup
initialize_spam_data()

class PremiumBot:
    def __init__(self):
        self.logger = logging.getLogger(__name__)
    
    def main_menu_keyboard(self):
        """Start message ka keyboard"""
        keyboard = types.InlineKeyboardMarkup(row_width=1)
        btn1 = types.InlineKeyboardButton("📢 Premium Demo", url=DEMO_CHANNEL_LINK)
        btn2 = types.InlineKeyboardButton("💰 Get Premium", callback_data="get_premium")
        btn3 = types.InlineKeyboardButton("❓ How To Get", callback_data="how_to_get")
        keyboard.add(btn1, btn2, btn3)
        return keyboard
    
    def payment_keyboard(self):
        """Sirf Payment Done ka button"""
        keyboard = types.InlineKeyboardMarkup(row_width=1)
        btn1 = types.InlineKeyboardButton("✅ Payment Done", callback_data="payment_done")
        btn2 = types.InlineKeyboardButton("📞 Support", url=f"https://t.me/{SUPPORT_USERNAME}")
        keyboard.add(btn1, btn2)
        return keyboard
    
    def after_payment_keyboard(self):
        """Payment ke baad ka keyboard"""
        keyboard = types.InlineKeyboardMarkup(row_width=1)
        btn1 = types.InlineKeyboardButton("🔄 Try Again", callback_data="get_premium")
        btn2 = types.InlineKeyboardButton("📞 Support", url=f"https://t.me/{SUPPORT_USERNAME}")
        keyboard.add(btn1, btn2)
        return keyboard
    
    def generate_qr_code(self, upi_id, amount, name):
        """Generate UPI QR code"""
        try:
            upi_url = f"upi://pay?pa={upi_id}&pn={name}&am={amount}&cu=INR"
            qr = qrcode.QRCode(version=1, box_size=10, border=4)
            qr.add_data(upi_url)
            qr.make(fit=True)
            img = qr.make_image(fill_color="black", back_color="white")
            img_bytes = BytesIO()
            img.save(img_bytes, format='PNG')
            img_bytes.seek(0)
            return img_bytes
        except Exception as e:
            self.logger.error(f"QR Error: {e}")
            return None

premium_bot = PremiumBot()

# ========== IMPORTANT LOGS ONLY ==========
def log_important_event(event_type, user_data=None):
    """Sirf important events log karo"""
    try:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        if event_type == "new_user":
            log_msg = f"""
🆕 <b>NEW USER</b>
👀 Name: {user_data.get('first_name', 'N/A')}
👤 User: @{user_data.get('username' , 'N/A')}
🆔 ID: <code>{user_data.get('id', 'N/A')}</code>
⏰ Time: {timestamp}
📊 Total Users: {len(users_data)}
            """
        elif event_type == "payment_attempt":
            log_msg = f"""
💰 <b>PAYMENT ATTEMPT</b>
👀 Name: {user_data.get('first_name', 'N/A')}
👤 User: @{user_data.get('username', 'N/A')}
🆔 ID: <code>{user_data.get('id', 'N/A')}</code>
⏰ Time: {timestamp}
            """
        elif event_type == "payment_failed":
            log_msg = f"""
❌ <b>PAYMENT FAILED</b>
👀 Name: {user_data.get('first_name', 'N/A')}
👤 User: @{user_data.get('username', 'N/A')}
⏰ Time: {timestamp}
            """
        else:
            return
        
        bot.send_message(LOG_CHANNEL, log_msg, parse_mode="HTML")
        
    except Exception as e:
        logging.error(f"Log error: {e}")

# ========== /IMPDATA COMMAND ==========
@bot.message_handler(commands=['impdata'])
def handle_impdata(message):
    """Import JSON data from file - ADMIN ONLY"""
    if str(message.from_user.id) != ADMIN_ID:
        bot.reply_to(message, "⛔ Admin access required!", parse_mode="HTML")
        return
    
    if not message.reply_to_message or not message.reply_to_message.document:
        help_text = """
<code>❌ Please reply to a JSON file with /impdata</code>

<b>📋 How to use:</b>
1. Prepare your JSON data file (users_data.json format)
2. Send the file to this chat
3. Reply to that file with <code>/impdata</code>

<b>📝 JSON Format Example:</b>
<pre>
{
    "123456789": {
        "id": 123456789,
        "username": "example_user",
        "first_name": "John",
        "last_name": "Doe",
        "start_time": "2024-01-01 12:00:00"
    }
}
</pre>

<b>⚠️ Note:</b>
• Existing users will be updated
• New users will be added
• Data will be saved to Railway persistent storage
        """
        bot.reply_to(message, help_text, parse_mode="HTML")
        return
    
    try:
        # Send initial status
        status_msg = bot.reply_to(message, "📥 <b>Downloading file...</b>", parse_mode="HTML")
        
        # Get file info
        file_info = bot.get_file(message.reply_to_message.document.file_id)
        file_name = message.reply_to_message.document.file_name
        
        if not file_name.lower().endswith('.json'):
            bot.edit_message_text(
                "❌ <b>File must be JSON format (.json extension required)</b>", 
                chat_id=message.chat.id, 
                message_id=status_msg.message_id,
                parse_mode="HTML"
            )
            return
        
        # Download file
        bot.edit_message_text(
            "⬇️ <b>Downloading file from Telegram...</b>", 
            chat_id=message.chat.id, 
            message_id=status_msg.message_id,
            parse_mode="HTML"
        )
        
        downloaded_file = bot.download_file(file_info.file_path)
        
        # Save temporarily
        temp_path = f"/tmp/{file_name}"
        with open(temp_path, 'wb') as f:
            f.write(downloaded_file)
        
        bot.edit_message_text(
            "🔍 <b>Reading and validating JSON data...</b>", 
            chat_id=message.chat.id, 
            message_id=status_msg.message_id,
            parse_mode="HTML"
        )
        
        # Read and parse JSON
        with open(temp_path, 'r', encoding='utf-8') as f:
            imported_data = json.load(f)
        
        # Validate data format
        if not isinstance(imported_data, dict):
            bot.edit_message_text(
                "❌ <b>Invalid JSON format. Must be a dictionary/object.</b>",
                chat_id=message.chat.id,
                message_id=status_msg.message_id,
                parse_mode="HTML"
            )
            os.remove(temp_path)
            return
        
        # Count users before import
        users_before = len(users_data)
        
        bot.edit_message_text(
            f"🔄 <b>Importing {len(imported_data)} user records...</b>",
            chat_id=message.chat.id,
            message_id=status_msg.message_id,
            parse_mode="HTML"
        )
        
        # Merge data (preserve existing, add new, update existing)
        imported_count = 0
        updated_count = 0
        skipped_count = 0
        error_count = 0
        
        for user_id_str, user_data in imported_data.items():
            try:
                # Validate required fields
                if not isinstance(user_data, dict):
                    error_count += 1
                    continue
                
                # Ensure user_id matches
                if 'id' not in user_data:
                    user_data['id'] = int(user_id_str) if user_id_str.isdigit() else 0
                
                if user_id_str in users_data:
                    # Update existing user
                    users_data[user_id_str].update(user_data)
                    updated_count += 1
                else:
                    # Add new user
                    users_data[user_id_str] = user_data
                    imported_count += 1
                    
                    # Initialize spam data for new user
                    if user_id_str not in spam_data:
                        spam_data[user_id_str] = {
                            "requests": [],
                            "warnings": 0,
                            "blocked_until": 0,
                            "block_level": 0,
                            "ban_reason": "",
                            "banned_by": 0
                        }
                    
            except Exception as e:
                error_count += 1
                print(f"Error importing user {user_id_str}: {e}")
        
        # Save to persistent storage
        save_users_data()
        save_spam_data()
        
        # Cleanup temp file
        os.remove(temp_path)
        
        # Send success message
        success_msg = f"""
✅ <b>DATA IMPORT COMPLETE!</b>

📊 <b>Import Statistics:</b>
┌──────────────────────────────┐
│ • Total users before: {users_before:>6} │
│ • Total users now: {len(users_data):>8} │
│ • New users imported: {imported_count:>5} │
│ • Existing users updated: {updated_count:>2} │
│ • Skipped/Errors: {error_count:>9} │
└──────────────────────────────┘

📁 <b>File processed:</b> {file_name}
💾 <b>Storage:</b> Railway Persistent Volume (/data)
⏰ <b>Time:</b> {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

<b>✅ Data successfully saved and ready to use!</b>
        """
        
        bot.edit_message_text(
            success_msg,
            chat_id=message.chat.id,
            message_id=status_msg.message_id,
            parse_mode="HTML"
        )
        
        # Also send to admin privately
        try:
            bot.send_message(
                ADMIN_ID, 
                f"✅ Data import complete!\n📊 Total users: {len(users_data)}\n📁 File: {file_name}",
                parse_mode="HTML"
            )
        except:
            pass
        
    except json.JSONDecodeError as e:
        error_msg = f"""
❌ <b>JSON PARSE ERROR</b>

<b>Error:</b> <code>{str(e)}</code>

<b>Possible issues:</b>
1. File is not valid JSON
2. File contains syntax errors
3. File encoding issues

<b>Please check your JSON file and try again.</b>
        """
        bot.edit_message_text(
            error_msg,
            chat_id=message.chat.id,
            message_id=status_msg.message_id,
            parse_mode="HTML"
        )
    except Exception as e:
        error_msg = f"""
❌ <b>IMPORT FAILED</b>

<b>Error:</b> <code>{str(e)}</code>

<b>Please check:</b>
1. File format is correct JSON
2. File size is not too large
3. You have proper permissions
        """
        bot.edit_message_text(
            error_msg,
            chat_id=message.chat.id,
            message_id=status_msg.message_id,
            parse_mode="HTML"
        )
        print(f"Import error: {e}")

# ========== /BAN COMMAND ==========
@bot.message_handler(commands=['ban'])
def handle_ban_user(message):
    """Ban a user manually for custom time"""
    if str(message.from_user.id) != ADMIN_ID:
        return  # Silent fail for non-admin
    
    # Parse command: /ban <user_id> <time> <unit> <reason (optional)>
    args = message.text.split()
    
    if len(args) < 3:
        help_text = """
<b>❌ Invalid Command Format</b>

<code>/ban &lt;user_id&gt; &lt;time&gt; &lt;unit&gt; [reason]</code>

<b>Examples:</b>
• <code>/ban 123456789 15 min spamming</code>
• <code>/ban 123456789 2 hour violation</code>
• <code>/ban 123456789 1 day permanent violation</code>

<b>Available Units:</b>
• <b>min</b> - minutes
• <b>hour</b> - hours  
• <b>day</b> - days
• <b>perm</b> - permanent (1 year)
        """
        bot.reply_to(message, help_text, parse_mode="HTML")
        return
    
    try:
        user_id = args[1]
        time_value = float(args[2])
        unit = args[3].lower() if len(args) > 3 else "min"
        reason = " ".join(args[4:]) if len(args) > 4 else "Admin ban"
        
        # Convert to seconds based on unit
        if unit == "min":
            duration_seconds = time_value * 60
            time_display = f"{int(time_value)} minutes"
        elif unit == "hour":
            duration_seconds = time_value * 3600
            time_display = f"{int(time_value)} hours"
        elif unit == "day":
            duration_seconds = time_value * 86400
            time_display = f"{int(time_value)} days"
        elif unit == "perm":
            duration_seconds = 31536000  # 1 year
            time_display = "permanent"
        else:
            bot.reply_to(message, "❌ Invalid unit. Use: min, hour, day, perm")
            return
        
        # Ban the user
        success = ban_user(user_id, duration_seconds, reason, message.from_user.id)
        
        if success:
            # Get user info if available
            user_info = ""
            if user_id in users_data:
                user_data = users_data[user_id]
                user_info = f"""
<b>User Info:</b>
• Name: {user_data.get('first_name', 'N/A')} {user_data.get('last_name', '')}
• Username: @{user_data.get('username', 'N/A')}
                """
            
            # Send confirmation to admin
            confirm_msg = f"""
✅ <b>USER BANNED SUCCESSFULLY</b>

<b>User ID:</b> <code>{user_id}</code>
<b>Duration:</b> {time_display}
<b>Reason:</b> {reason}
<b>Banned By:</b> @{message.from_user.username if message.from_user.username else message.from_user.id}
{user_info}

<b>User has been notified about the ban.</b>
            """
            
            bot.reply_to(message, confirm_msg, parse_mode="HTML")
            
            # Log to admin log channel
            try:
                log_msg = f"""
🔨 <b>ADMIN BAN</b>

👤 User ID: <code>{user_id}</code>
⏰ Duration: {time_display}
📝 Reason: {reason}
👮 Banned By: @{message.from_user.username if message.from_user.username else message.from_user.id}
🕒 Time: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
                """
                bot.send_message(LOG_CHANNEL, log_msg, parse_mode="HTML")
            except:
                pass
            
        else:
            bot.reply_to(message, "❌ Failed to ban user")
            
    except ValueError:
        bot.reply_to(message, "❌ Invalid time value. Time must be a number.")
    except Exception as e:
        logging.error(f"Ban error: {e}")
        bot.reply_to(message, f"❌ Error: {str(e)}")

# ========== /SETSTARTMSG COMMAND ==========
@bot.message_handler(commands=['setstartmsg'])
def handle_set_start_message(message):
    """Admin can set custom start message with media"""
    if str(message.from_user.id) != ADMIN_ID:
        return  # Silent fail, no response to non-admin
    
    if not message.reply_to_message:
        bot.reply_to(message, "❌ Reply to a message with /setstartmsg")
        return
    
    replied_msg = message.reply_to_message
    
    # Store message data
    start_message_data['text'] = replied_msg.caption or replied_msg.text or ""
    start_message_data['has_media'] = False
    
    # Check for media
    if replied_msg.photo:
        start_message_data['media_type'] = 'photo'
        start_message_data['file_id'] = replied_msg.photo[-1].file_id
        start_message_data['has_media'] = True
    elif replied_msg.video:
        start_message_data['media_type'] = 'video'
        start_message_data['file_id'] = replied_msg.video.file_id
        start_message_data['has_media'] = True
    elif replied_msg.document:
        start_message_data['media_type'] = 'document'
        start_message_data['file_id'] = replied_msg.document.file_id
        start_message_data['has_media'] = True
    elif replied_msg.animation:
        start_message_data['media_type'] = 'animation'
        start_message_data['file_id'] = replied_msg.animation.file_id
        start_message_data['has_media'] = True
    
    # Save to file
    save_start_message()
    
    bot.reply_to(message, "✅ Start message updated!")

# ========== /START COMMAND ==========
@bot.message_handler(commands=['start'])
def handle_start(message):
    """Handle /start command with custom message"""
    try:
        user_id = message.from_user.id
        
        # Check for spam (FIRST THING TO CHECK)
        spam_result = check_spam(user_id)
        if spam_result:
            try:
                bot.send_message(message.chat.id, spam_result, parse_mode="HTML")
            except Exception as e:
                logging.error(f"Spam message send error: {e}")
            return
        
        # Check if new user
        is_new_user = str(user_id) not in users_data
        
        # Store user data
        users_data[str(user_id)] = {
            'id': user_id,
            'username': message.from_user.username,
            'first_name': message.from_user.first_name,
            'last_name': message.from_user.last_name or "",
            'start_time': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        
        # Auto-save every 10 new users
        if is_new_user:
            if len(users_data) % 10 == 0:
                save_users_data()
            else:
                # Quick save for single user
                try:
                    with open(USERS_DATA_FILE, 'w') as f:
                        json.dump(users_data, f, indent=4)
                except:
                    pass
        
        # Reset spam counter for legit users
        reset_spam_counter(user_id)
        
        # Log only for new users
        if is_new_user:
            log_important_event("new_user", users_data[str(user_id)])
        
        # Check if custom start message exists
        if start_message_data and 'has_media' in start_message_data:
            # Send custom start message
            text = start_message_data.get('text', "")
            
            if start_message_data['has_media']:
                media_type = start_message_data.get('media_type', '')
                file_id = start_message_data.get('file_id', '')
                
                if media_type == 'photo' and file_id:
                    bot.send_photo(
                        message.chat.id,
                        photo=file_id,
                        caption=text,
                        reply_markup=premium_bot.main_menu_keyboard(),
                        parse_mode="HTML"
                    )
                elif media_type == 'video' and file_id:
                    bot.send_video(
                        message.chat.id,
                        video=file_id,
                        caption=text,
                        reply_markup=premium_bot.main_menu_keyboard(),
                        parse_mode="HTML"
                    )
                elif media_type == 'document' and file_id:
                    bot.send_document(
                        message.chat.id,
                        document=file_id,
                        caption=text,
                        reply_markup=premium_bot.main_menu_keyboard(),
                        parse_mode="HTML"
                    )
                elif media_type == 'animation' and file_id:
                    bot.send_animation(
                        message.chat.id,
                        animation=file_id,
                        caption=text,
                        reply_markup=premium_bot.main_menu_keyboard(),
                        parse_mode="HTML"
                    )
                else:
                    # Fallback to default message
                    send_default_start_message(message)
            else:
                # Only text message
                bot.send_message(
                    message.chat.id,
                    text,
                    reply_markup=premium_bot.main_menu_keyboard(),
                    parse_mode="HTML"
                )
        else:
            # Send default start message
            send_default_start_message(message)
        
    except Exception as e:
        logging.error(f"Start error: {e}")

def send_default_start_message(message):
    """Default start message if custom not set"""
    welcome_text = f"""
<b>🔥 PREMIUM CONTENT 🔥</b>

• Price: <b>₹{AMOUNT}/- only</b>
• Videos: <b>55k+ VIDEOS</b>
• Access: <b>Lifetime</b>

<b>Tap "Get Premium" to Buy</b>
    """
    
    bot.send_message(
        message.chat.id,
        welcome_text,
        reply_markup=premium_bot.main_menu_keyboard(),
        parse_mode="HTML"
    )

# ========== GET PREMIUM ==========
@bot.callback_query_handler(func=lambda call: call.data == "get_premium")
def handle_get_premium(call):
    """Get Premium click - DIRECT QR CODE GENERATE"""
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    
    # Check for spam (FIRST THING TO CHECK)
    spam_result = check_spam(user_id)
    if spam_result:
        try:
            bot.send_message(chat_id, spam_result, parse_mode="HTML")
        except:
            pass
        bot.answer_callback_query(call.id)
        return
    
    # Reset spam counter for legit users
    reset_spam_counter(user_id)
    
    # Log payment attempt
    if str(user_id) in users_data:
        log_important_event("payment_attempt", users_data[str(user_id)])
    
    # Generate QR code
    qr_image = premium_bot.generate_qr_code(UPI_ID, AMOUNT, UPI_NAME)
    
    if qr_image:
        caption = f"""
<b>💰 PAY ₹{AMOUNT} FOR PREMIUM</b>

<b>UPI Details:</b>
└ ID: <code>{UPI_ID}</code>
└ Name: {UPI_NAME}
└ Amount: <b>₹{AMOUNT}</b>

<b>Instructions:</b>
1. Scan QR with any UPI app
2. Pay ₹{AMOUNT}
3. Click "Payment Done" below
        """
        
        # Send QR code with Payment Done button
        bot.send_photo(
            chat_id,
            photo=qr_image,
            caption=caption,
            reply_markup=premium_bot.payment_keyboard()
        )
    else:
        manual_text = f"""
<b>💰 PAY ₹{AMOUNT}</b>

<b>UPI ID:</b> <code>{UPI_ID}</code>
<b>Amount:</b> ₹{AMOUNT}

<b>Steps:</b>
1. Send ₹{AMOUNT} to above UPI ID
2. Click "Payment Done"
        """
        
        bot.send_message(
            chat_id,
            manual_text,
            reply_markup=premium_bot.payment_keyboard()
        )
    
    bot.answer_callback_query(call.id)

# ========== HOW TO GET ==========
@bot.callback_query_handler(func=lambda call: call.data == "how_to_get")
def handle_how_to_get(call):
    """How to get premium instructions"""
    user_id = call.from_user.id
    
    # Check for spam (FIRST THING TO CHECK)
    spam_result = check_spam(user_id)
    if spam_result:
        try:
            bot.send_message(call.message.chat.id, spam_result, parse_mode="HTML")
        except:
            pass
        bot.answer_callback_query(call.id)
        return
    
    # Reset spam counter for legit users
    reset_spam_counter(user_id)
    
    instructions = f"""
<b>❓ HOW TO GET PREMIUM:</b>

1. Click "Get Premium" button
2. Scan QR code and pay ₹{AMOUNT}
3. Click "Payment Done" button
4. Wait 10 seconds for verification

<b>Support:</b> @{SUPPORT_USERNAME}
    """
    
    try:
        bot.edit_message_text(
            instructions,
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            reply_markup=premium_bot.main_menu_keyboard()
        )
    except:
        bot.send_message(
            call.message.chat.id,
            instructions,
            reply_markup=premium_bot.main_menu_keyboard()
        )
    
    bot.answer_callback_query(call.id)

# ========== PAYMENT DONE ==========
@bot.callback_query_handler(func=lambda call: call.data == "payment_done")
def handle_payment_done(call):
    """Payment Done clicked"""
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    
    # Check for spam (FIRST THING TO CHECK)
    spam_result = check_spam(user_id)
    if spam_result:
        try:
            bot.send_message(chat_id, spam_result, parse_mode="HTML")
        except:
            pass
        bot.answer_callback_query(call.id)
        return
    
    # Reset spam counter for legit users
    reset_spam_counter(user_id)
    
    # Delete previous message
    try:
        bot.delete_message(chat_id, call.message.message_id)
    except:
        pass
    
    # Send processing message
    processing_msg = bot.send_message(
        chat_id,
        "🔍 <b>Verifying Payment...</b>\n\n⏳ Please wait 10 seconds...",
    )
    
    bot.answer_callback_query(call.id)
    
    # Start background processing
    thread = threading.Thread(
        target=process_payment,
        args=(chat_id, processing_msg.message_id, user_id)
    )
    thread.start()

def process_payment(chat_id, message_id, user_id):
    """10 second payment processing"""
    try:
        # 10 second loading animation
        for i in range(10):
            dots = "⏳⌛🔍📊"
            progress = "█" * (i+1) + "░" * (10-i-1)
            
            status = f"""
<b>{dots[i%4]} Processing...</b>

Progress: [{progress}] {(i+1)*10}%
            """
            
            try:
                bot.edit_message_text(
                    status,
                    chat_id=chat_id,
                    message_id=message_id
                )
            except:
                pass
            
            time.sleep(1)
        
        # After 10 seconds - Payment Not Received
        failed_msg = f"""
<b>❌ PAYMENT NOT RECEIVED</b>

<b>What to do:</b>
1. Check payment in UPI app
2. Ensure ₹{AMOUNT} sent to <code>{UPI_ID}</code>
3. Try payment again
4. Contact @{SUPPORT_USERNAME}
        """
        
        # Log payment failure
        if str(user_id) in users_data:
            log_important_event("payment_failed", users_data[str(user_id)])
        
        bot.edit_message_text(
            failed_msg,
            chat_id=chat_id,
            message_id=message_id,
            reply_markup=premium_bot.after_payment_keyboard()
        )
        
    except Exception as e:
        logging.error(f"Payment processing error: {e}")

# ========== OTHER ADMIN COMMANDS ==========
@bot.message_handler(commands=['stats'])
def handle_stats(message):
    """Show bot stats - Admin only"""
    if str(message.from_user.id) != ADMIN_ID:
        return
    
    current_time = time.time()
    blocked_users = sum(1 for u in spam_data.values() if u.get("blocked_until", 0) > current_time)
    
    stats_text = f"""
<b>📊 BOT STATISTICS</b>

👥 <b>Users:</b>
• Total Users: {len(users_data)}
• New Today: {sum(1 for u in users_data.values() if u.get('start_time', '').startswith(datetime.now().strftime('%Y-%m-%d')))}

🛡️ <b>Spam Protection:</b>
• Tracked Users: {len(spam_data)}
• Currently Blocked: {blocked_users}
• Max Spam Count: {MAX_SPAM_COUNT}
• Time Window: {SPAM_TIME_WINDOW}s

💰 <b>Payment Info:</b>
• UPI ID: <code>{UPI_ID}</code>
• Amount: ₹{AMOUNT}
• Name: {UPI_NAME}

📁 <b>Storage:</b>
• Data Directory: {DATA_DIR}
• Files: {sum(1 for f in os.listdir(DATA_DIR) if f.endswith('.json'))} JSON files

🚀 <b>Status:</b> ✅ Running on Railway
    """
    bot.reply_to(message, stats_text, parse_mode="HTML")

@bot.message_handler(commands=['backup'])
def handle_backup(message):
    """Create backup of all data"""
    if str(message.from_user.id) != ADMIN_ID:
        return
    
    try:
        # Create backup data
        backup_data = {
            "users": users_data,
            "spam": spam_data,
            "start_message": start_message_data,
            "backup_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "total_users": len(users_data),
            "total_spam_users": len(spam_data)
        }
        
        # Save backup file
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_file = f"backup_{timestamp}.json"
        backup_path = os.path.join(DATA_DIR, backup_file)
        
        with open(backup_path, 'w') as f:
            json.dump(backup_data, f, indent=4)
        
        # Send to admin
        with open(backup_path, 'rb') as f:
            bot.send_document(
                message.chat.id, 
                f, 
                caption=f"📦 Backup: {len(users_data)} users, {len(spam_data)} spam records\n⏰ {timestamp}"
            )
        
        print(f"✅ Backup created: {backup_file}")
        
    except Exception as e:
        bot.reply_to(message, f"❌ Backup failed: {str(e)}")

@bot.message_handler(commands=['savedata'])
def handle_save_data(message):
    """Force save all data to disk"""
    if str(message.from_user.id) != ADMIN_ID:
        return
    
    try:
        save_all_data()
        bot.reply_to(message, f"✅ All data saved!\n👥 Users: {len(users_data)}\n🛡️ Spam: {len(spam_data)}")
    except Exception as e:
        bot.reply_to(message, f"❌ Save failed: {str(e)}")

@bot.message_handler(commands=['getstartmsg'])
def handle_get_start_message(message):
    """View current start message"""
    if str(message.from_user.id) != ADMIN_ID:
        return
    
    if not start_message_data:
        bot.reply_to(message, "❌ No custom start message set")
        return
    
    media_type = start_message_data.get('media_type', 'text')
    has_media = start_message_data.get('has_media', False)
    text_preview = (start_message_data.get('text', '')[:100] + '...') if len(start_message_data.get('text', '')) > 100 else start_message_data.get('text', '')
    
    info_msg = f"""
<b>📋 CURRENT START MESSAGE</b>

<b>Type:</b> {media_type if has_media else 'Text Only'}
<b>Has Media:</b> {'✅ Yes' if has_media else '❌ No'}
<b>Preview:</b> {text_preview}

<b>File Location:</b> <code>{START_MESSAGE_FILE}</code>
    """
    
    bot.reply_to(message, info_msg, parse_mode="HTML")

@bot.message_handler(commands=['clearstartmsg'])
def handle_clear_start_message(message):
    """Clear custom start message"""
    if str(message.from_user.id) != ADMIN_ID:
        return
    
    global start_message_data
    start_message_data = {}
    save_start_message()
    
    bot.reply_to(message, "✅ Custom start message cleared")

# ========== SILENT HANDLER ==========
@bot.message_handler(func=lambda message: True)
def handle_all_messages(message):
    """Silent handler - no response to random messages"""
    if message.text and message.text.startswith('/'):
        # Unknown command - ignore
        pass
    # No response for random messages

# ========== START BOT ==========
if __name__ == "__main__":
    print("=" * 60)
    print("🤖 PREMIUM TELEGRAM BOT - RAILWAY DEPLOYMENT")
    print("=" * 60)
    
    # Check environment variables
    if not BOT_TOKEN or BOT_TOKEN == "7928198485:AAER_Ds7PA5nVKKHEm-7-PWDVVixP4S28Mo":
        print("⚠️  WARNING: Using default BOT_TOKEN")
        print("💡 Tip: Set BOT_TOKEN in Railway Environment Variables")
    
    print(f"✅ Bot Token: {BOT_TOKEN[:15]}...")
    print(f"✅ Admin ID: {ADMIN_ID}")
    print(f"✅ Users Loaded: {len(users_data)}")
    print(f"✅ Data Directory: {DATA_DIR}")
    print(f"✅ UPI ID: {UPI_ID}")
    print(f"✅ Amount: ₹{AMOUNT}")
    print(f"✅ Spam Protection: Active (Max: {MAX_SPAM_COUNT} in {SPAM_TIME_WINDOW}s)")
    print("=" * 60)
    print("📋 Available Admin Commands:")
    print("• /impdata - Import JSON data (reply to file)")
    print("• /stats - Show bot statistics")
    print("• /backup - Download data backup")
    print("• /savedata - Force save all data")
    print("• /ban - Ban a user")
    print("• /setstartmsg - Set custom start message")
    print("=" * 60)
    print("🚀 Bot is starting...")
    print("=" * 60)
    
    try:
        bot.infinity_polling()
    except Exception as e:
        print(f"❌ Bot Error: {e}")
        print("🔄 Attempting to restart in 10 seconds...")
        time.sleep(10)
        # Restart by exiting - Railway will auto-restart
        sys.exit(1)
