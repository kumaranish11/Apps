import telebot
import requests
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

# Yahan apne "Master Bot" ka token dalein (Jisse aap command denge)
MASTER_TOKEN = "8631991712:AAEuNPGYNC_MB8KW6IKC4HqZD15GvjFl3cU"
bot = telebot.TeleBot(MASTER_TOKEN)

# User ka data save karne ke liye
user_data = {}

# Jab aap /start bhejenge
@bot.message_handler(commands=['start'])
def start_message(message):
    msg = bot.send_message(message.chat.id, "👋 Welcome! Mujhe us **Target Bot ka Token** dein jiska aap use karna chahte hain:")
    bot.register_next_step_handler(msg, process_bot_token)

# Token check karne ka function
def process_bot_token(message):
    token = message.text.strip()
    chat_id = message.chat.id
    
    bot.send_message(chat_id, "⏳ Token verify kar raha hoon...")
    req = requests.get(f"https://api.telegram.org/bot{token}/getMe")
    
    if req.status_code == 200:
        bot_info = req.json()['result']
        bot_id = bot_info['id'] # Target Bot ka apna ID
        
        # Token aur Bot ID save karna
        user_data[chat_id] = {
            'token': token,
            'bot_id': bot_id,
            'bot_username': bot_info['username']
        }
        
        # Inline Buttons banana
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("📝 Channel Me Post Karo", callback_data="menu_post"))
        markup.add(InlineKeyboardButton("🤖 Bot Ki DP Change Karo", callback_data="menu_bot_dp"))
        
        bot.send_message(
            chat_id, 
            f"✅ Token verify ho gaya! \nTarget Bot: @{bot_info['username']}\n\nAb niche se option select karein:", 
            reply_markup=markup
        )
    else:
        bot.send_message(chat_id, "❌ Galat Token! Dobara /start likhein.")

# Button click ko handle karna
@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    chat_id = call.message.chat.id
    if chat_id not in user_data:
        bot.send_message(chat_id, "⚠️ Pehle /start karke token dein.")
        return

    if call.data == "menu_post":
        msg = bot.send_message(
            chat_id, 
            "Bhai, ab message is format me bhejein:\n\n`t.me/channel_link Aapka Message 10x`\n\n*(Jahan 10x ka matlab 10 bar post hoga)*",
            parse_mode="Markdown"
        )
        bot.register_next_step_handler(msg, handle_multi_post)
        
    elif call.data == "menu_bot_dp":
        bot_username = user_data[chat_id]['bot_username']
        msg = bot.send_message(
            chat_id, 
            f"Theek hai, ab wo Photo bhejein jo aapko @{bot_username} ki DP par lagani hai:"
        )
        bot.register_next_step_handler(msg, change_target_bot_dp)

# ----------------- 1. MULTI POST LOGIC -----------------

def handle_multi_post(message):
    chat_id = message.chat.id
    text = message.text.strip()
    token = user_data[chat_id]['token']
    
    parts = text.split()
    
    # Format check karna (Kam se kam 3 word aur aakhir me 'x')
    if len(parts) >= 3 and parts[-1].lower().endswith('x') and parts[-1][:-1].isdigit():
        channel_link = parts[0]
        count = int(parts[-1][:-1]) 
        msg_text = " ".join(parts[1:-1]) 
        
        # Link ko username me convert karna
        if "t.me/" in channel_link:
            channel = "@" + channel_link.split("t.me/")[-1]
        else:
            channel = channel_link if channel_link.startswith("@") else "@" + channel_link
            
        bot.send_message(chat_id, f"🚀 {channel} me '{msg_text}' {count} bar bhejna shuru kar raha hoon...")
        
        success = 0
        for i in range(count):
            res = requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage", 
                data={'chat_id': channel, 'text': msg_text}
            )
            if res.status_code == 200:
                success += 1
                
        if success > 0:
            bot.send_message(chat_id, f"✅ Done! {success}/{count} messages post ho gaye!")
        else:
             bot.send_message(chat_id, f"❌ Post fail. Check karein Target bot {channel} ka admin hai ya nahi.")
    else:
        bot.send_message(chat_id, "❌ Format galat hai. Is tarah bhejein: \nt.me/MyChannel Hi 10x \n\nDobara koshish ke liye /start dabayein.")


# ----------------- 2. BOT DP CHANGE LOGIC -----------------

def change_target_bot_dp(message):
    chat_id = message.chat.id
    
    # Check karna ke photo bheji hai ya nahi
    if not message.photo:
        bot.send_message(chat_id, "❌ Yeh photo nahi hai. Process cancel. /start dabayein.")
        return
        
    token = user_data[chat_id]['token']
    target_bot_id = user_data[chat_id]['bot_id']
    
    bot.send_message(chat_id, "⚡ Target Bot ki DP change ki jaa rahi hai...")
    
    try:
        # Photo ko Master Bot se download karna
        file_info = bot.get_file(message.photo[-1].file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        
        # Target Bot ka Token use karke setChatPhoto API call karna
        res = requests.post(
            f"https://api.telegram.org/bot{token}/setChatPhoto",
            data={'chat_id': target_bot_id},
            files={'photo': ('dp.jpg', downloaded_file, 'image/jpeg')}
        )
        
        if res.status_code == 200:
            bot.send_message(chat_id, "✅ Done! Target Bot ki DP successfully change ho gayi!")
        else:
            bot.send_message(chat_id, f"❌ Kuch masla aagaya. Error: {res.text}")
            
    except Exception as e:
        bot.send_message(chat_id, f"❌ Error: {e}")

# Bot ko run karna
print("Master Bot start ho gaya hai! Enjoy karo bhai...")
bot.polling(none_stop=True)

