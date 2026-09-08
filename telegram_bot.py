import os, glob, logging, asyncio
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters
from telegram.request import HTTPXRequest

logging.getLogger("httpx").setLevel(logging.WARNING)

TOKEN = "8837097327:AAHQxtrn1Pi53M4qA3ElwbeCKu8mUUUhdl4"

async def search_and_download_audio(query):
    for f in glob.glob("temp_song.*"):
        try: os.remove(f)
        except: pass

    search_query = f"ytsearch1:{query} audio"
    
    # Ambil judul asli dari metadata YouTube
    info_cmd = f'yt-dlp --print "%(title)s|%(uploader)s" --no-playlist "{search_query}"'
    proc_info = await asyncio.create_subprocess_shell(
        info_cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL
    )
    stdout_info, _ = await proc_info.communicate()
    
    title_real = "Unknown Title"
    artist_real = "Yuki Music"
    if stdout_info:
        info_text = stdout_info.decode().strip()
        if "|" in info_text:
            title_real, artist_real = info_text.split("|", 1)

    # Unduh file audio
    cmd = f'yt-dlp -x --audio-format mp3 -o "temp_song.%(ext)s" --no-playlist "{search_query}"'
    process = await asyncio.create_subprocess_shell(
        cmd,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL
    )
    await process.communicate()
    
    files = glob.glob("temp_song.mp3")
    if files:
        return files[0], title_real, artist_real
    return None, None, None

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    chat_id = update.effective_chat.id
    
    if text.lower().startswith("putar"):
        query = text[5:].strip()
        if not query:
            await update.message.reply_text("Ketik: 'putar [judul lagu/artis]'")
            return

        status_msg = await update.message.reply_text(f"🔍 Mencari lagu online: '{query}'...")
        
        try:
            file_path, real_title, real_artist = await search_and_download_audio(query)
            if file_path and os.path.exists(file_path):
                await context.bot.edit_message_text(
                    chat_id=chat_id, 
                    message_id=status_msg.message_id, 
                    text="🎶 Mengirimkan audio..."
                )
                with open(file_path, 'rb') as audio:
                    await context.bot.send_audio(
                        chat_id=chat_id, 
                        audio=audio,
                        title=real_title,
                        performer=real_artist,
                        caption=f"🎵 {real_title}\n👤 {real_artist}"
                    )
                try: os.remove(file_path)
                except: pass
            else:
                await context.bot.edit_message_text(
                    chat_id=chat_id, 
                    message_id=status_msg.message_id, 
                    text="❌ Lagu tidak ditemukan."
                )
        except Exception as e:
            await update.message.reply_text(f"❌ Error: {str(e)}")
    else:
        await update.message.reply_text("Yuki di sini! Ketik 'putar [judul]' untuk memutar musik.")

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    print(f"⚠️ Peringatan Jaringan: {context.error}")

if __name__ == '__main__':
    # Mengatur request timeout lebih longgar (60 detik) agar tidak gampang ConnectTimeout
    request = HTTPXRequest(connect_timeout=60.0, read_timeout=60.0)
    app = ApplicationBuilder().token(TOKEN).request(request).build()
    
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    app.add_error_handler(error_handler)
    
    print("✅ Bot Yuki Siap (Timeout Longgar & Auto-Detect Judul)!")
    app.run_polling(bootstrap_retries=5)
