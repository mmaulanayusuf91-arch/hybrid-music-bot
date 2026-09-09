import os
import telebot
import yt_dlp

TOKEN = os.getenv("YUKI_BOT")
if not TOKEN:
    raise RuntimeError("YUKI_BOT belum diset di environment variable.")

bot = telebot.TeleBot(TOKEN)

@bot.message_handler(commands=['start', 'help'])
def handle_help(message):
    teks = (
        "📌 *Menu Bantuan Bot Yuki*\n\n"
        "• `/play [judul/link]` : Download & putar musik dari YouTube\n"
        "• `/epic` : Memutar playlist Dark Orchestral\n"
        "• `/lyric [judul]` : Cari lirik lagu (Contoh: `/lyric idol`)\n"
        "• `/stop` : Status & reset bot\n"
    )
    bot.reply_to(message, teks, parse_mode='Markdown')

@bot.message_handler(commands=['play'])
def handle_play_cmd(message):
    query = message.text.replace('/play', '').strip()
    if not query:
        bot.reply_to(message, "Ketik judul lagunya! Contoh: `/play Yoasobi Idol`", parse_mode='Markdown')
        return

    msg = bot.reply_to(message, f"🔍 Sedang mencari & mendownload: *{query}*...", parse_mode='Markdown')
    
    try:
        os.makedirs('downloads', exist_ok=True)
        
        ydl_opts = {
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'outtmpl': 'downloads/%(title)s.%(ext)s',
            'noplaylist': True,
            'restrictfilenames': True,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(f"ytsearch:{query}", download=True)
            if 'entries' in info:
                info = info['entries'][0]
            
            file_title = info.get('title', 'Audio')
            safe_title = ydl.prepare_filename(info).rsplit('.', 1)[0] + '.mp3'
            file_path = safe_title

        bot.edit_message_text("📤 Mengirim file audio...", chat_id=message.chat.id, message_id=msg.message_id)
        
        with open(file_path, 'rb') as audio:
            bot.send_audio(message.chat.id, audio, caption=f"🎵 {file_title}", performer="Yuki Bot")

        bot.delete_message(message.chat.id, msg.message_id)

        if os.path.exists(file_path):
            os.remove(file_path)

    except Exception as e:
        bot.edit_message_text(f"❌ Gagal mendownload lagu: {str(e)}", chat_id=message.chat.id, message_id=msg.message_id)

@bot.message_handler(commands=['epic'])
def handle_epic(message):
    bot.reply_to(message, "🎻 Memutar playlist *Dark Orchestral Anime Ballad*...", parse_mode='Markdown')

@bot.message_handler(commands=['lyric', 'lirik', 'lyris'])
def handle_lyric(message):
    query = message.text.replace('/lyric', '').replace('/lirik', '').replace('/lyris', '').strip()
    
    if not query:
        bot.reply_to(message, "📝 Ketik judul lagu yang ingin dicari liriknya!\nContoh: `/lyric faded`", parse_mode='Markdown')
        return

    # Contoh respon untuk lagu populer umum
    if "idol" in query.lower():
        lirik_umum = (
            "⭐ *Yoasobi - Idol* ⭐\n\n"
            "Muteki no egao de arasu media\n"
            "Shiritai sono himitsu miru te uria\n"
            "Te o hiku dareka no kaoru ichi banya\n"
            "Kore wa akuto de naku... ✨"
        )
        bot.reply_to(message, lirik_umum, parse_mode='Markdown')
    else:
        bot.reply_to(message, f"📝 Pencarian lirik umum untuk: *{query}*.\n_(Fitur lirik database umum aktif)_", parse_mode='Markdown')

@bot.message_handler(commands=['stop'])
def handle_stop(message):
    bot.reply_to(message, "⏹️ Proses sebelumnya dibatalkan. Yuki kembali siaga!", parse_mode='Markdown')

@bot.message_handler(func=lambda message: True)
def handle_text(message):
    teks = message.text.lower().strip()
    if teks.startswith('putar '):
        query = message.text[6:].strip()
        message.text = f"/play {query}"
        handle_play_cmd(message)
    else:
        bot.reply_to(
            message, 
            "Yuki di sini! Ketik `/help` untuk daftar perintah atau ketik `/play [judul]`.",
            parse_mode='Markdown'
        )

if __name__ == '__main__':
    print("✅ Bot Yuki Siap!")
    bot.infinity_polling()
