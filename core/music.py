import subprocess
import tempfile
import os


def search_and_download_audio(query):
    """
    Yuki Music Core
    Mencari lagu dan mengunduh audio MP3.
    Bisa dipakai oleh Telegram, WhatsApp, dan platform lain.
    """

    if not query or not query.strip():
        return None

    query = query.strip()

    # Folder sementara khusus untuk setiap request
    temp_dir = tempfile.mkdtemp(prefix="yuki_music_")
    output_template = os.path.join(temp_dir, "audio.%(ext)s")

    search_query = f"ytsearch1:{query} audio"

    try:
        # Ambil metadata lagu
        info = subprocess.run(
            [
                "yt-dlp",
                "--print",
                "%(title)s|%(uploader)s",
                "--no-playlist",
                search_query
            ],
            capture_output=True,
            text=True,
            timeout=60
        )

        title = "Unknown Title"
        artist = "Yuki Music"

        if info.returncode == 0 and info.stdout.strip():
            result = info.stdout.strip().splitlines()[0]

            if "|" in result:
                title, artist = result.split("|", 1)

        # Download audio
        download = subprocess.run(
            [
                "yt-dlp",
                "-x",
                "--audio-format", "mp3",
                "-o", output_template,
                "--no-playlist",
                search_query
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            timeout=180
        )

        if download.returncode != 0:
            return None

        audio_file = os.path.join(temp_dir, "audio.mp3")

        if not os.path.exists(audio_file):
            return None

        return {
            "file": audio_file,
            "title": title.strip(),
            "artist": artist.strip()
        }

    except Exception as e:
        print(f"❌ Yuki Music Core Error: {e}")
        return None

