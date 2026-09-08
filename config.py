"""
config.py
=========
Semua konstanta konfigurasi terpusat di sini agar assistant.py dan
battery_monitor.py tidak perlu hardcode path/nilai di banyak tempat.

CATATAN PENTING:
- Jangan taruh API key di sini. API key WAJIB diambil dari environment
  variable (lihat setup.sh / README bagian "cara menjalankan").
- Sesuaikan APP_PACKAGES dan MUSIC_DIR dengan kondisi HP kamu sendiri.
"""

import os

# ---------------------------------------------------------------------------
# PATH DASAR
# ---------------------------------------------------------------------------

# Direktori tempat file-file assistant berada (folder project ini).
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Folder musik lokal. Diarahkan ke folder Music asli di HP (lewat
# symlink Termux ~/storage yang dibuat oleh `termux-setup-storage`),
# supaya semua lagu yang sudah ada di penyimpanan umum HP langsung
# terbaca tanpa perlu dipindah ke folder proyek.
MUSIC_DIR = "music"

# File memory percakapan (maks MEMORY_LIMIT pesan, lihat di bawah).
MEMORY_FILE = os.path.join(BASE_DIR, "memory.json")

# Logging.
LOG_DIR = os.path.join(BASE_DIR, "logs")
LOG_FILE = os.path.join(LOG_DIR, "assistant.log")
LOG_MAX_BYTES = 512 * 1024   # 512 KB per file log, biar tidak membengkak
LOG_BACKUP_COUNT = 2         # simpan maksimal 2 file backup log lama

# State baterai (dipakai battery_monitor.py, path terpisah dari memory).
BATTERY_STATE_FILE = os.path.join(BASE_DIR, "battery_state.json")

# ---------------------------------------------------------------------------
# APLIKASI LOKAL (LOCAL APP COMMAND)
# ---------------------------------------------------------------------------
# PENTING: package name di bawah ini HANYA CONTOH/PLACEHOLDER.
# Package name berbeda-beda tergantung region, versi, atau apakah aplikasi
# terinstal dari Play Store/APK pihak ketiga. Cara mengecek package name
# yang BENAR-BENAR terpasang di HP kamu:
#
#   pm list packages | grep -i genshin
#   pm list packages | grep -i youtube
#   pm list packages | grep -i whatsapp
#
# Setelah dapat nama package-nya, tes dulu manual sebelum dipakai:
#
#   monkey -p com.contoh.package -c android.intent.category.LAUNCHER 1
#
# Kalau aplikasi tidak terbuka / monkey error, berarti package name salah
# atau aplikasi tidak mendukung intent LAUNCHER standar.
APP_PACKAGES = {
    "genshin": "com.miHoYo.GenshinImpact",   # contoh umum, CEK ULANG di HP kamu
    "youtube": "com.google.android.youtube",
    "chrome": "com.android.chrome",
    "whatsapp": "com.whatsapp",
}

# ---------------------------------------------------------------------------
# MUSIK
# ---------------------------------------------------------------------------
SUPPORTED_MUSIC_EXT = (".mp3", ".m4a", ".wav", ".ogg", ".flac")

# Ambang batas skor fuzzy (0.0-1.0) memakai difflib.SequenceMatcher.ratio()
# saat tidak ada kata query yang cocok sama sekali di nama file -- untuk
# menoleransi typo ringan (mis. "bohemia" vs "bohemian"). Di bawah ambang
# ini dianggap tidak cocok sama sekali.
MUSIC_FUZZY_MATCH_THRESHOLD = 0.6

# ---------------------------------------------------------------------------
# DETEKSI ONLINE/OFFLINE
# ---------------------------------------------------------------------------
# Host:port ringan untuk tes koneksi TCP (bukan ICMP/ping, karena ICMP
# banyak diblokir oleh firewall/operator). Beberapa host disediakan agar
# jika satu host down/diblokir, masih bisa fallback ke host lain.
ONLINE_CHECK_HOSTS = [
    ("1.1.1.1", 53),   # Cloudflare DNS
    ("8.8.8.8", 53),   # Google DNS
]
ONLINE_CHECK_TIMEOUT = 2.5  # detik, harus pendek sesuai spesifikasi

# ---------------------------------------------------------------------------
# LLM PROVIDER
# ---------------------------------------------------------------------------
# Pilihan: "groq" atau "gemini"
LLM_PROVIDER = "groq"

# Model default per provider (bisa diganti sesuai kebutuhan/ketersediaan).
GROQ_MODEL = "llama-3.1-8b-instant"
GEMINI_MODEL = "gemini-1.5-flash"

# Nama environment variable yang WAJIB di-set sebelum menjalankan assistant.
GROQ_API_KEY_ENV = "GROQ_API_KEY"
GEMINI_API_KEY_ENV = "GEMINI_API_KEY"

# Timeout request ke LLM API (detik).
LLM_REQUEST_TIMEOUT = 20

# ---------------------------------------------------------------------------
# MEMORY PERCAKAPAN
# ---------------------------------------------------------------------------
MEMORY_LIMIT = 10          # maksimal 10 pesan tersimpan (bukan 10 pasang)
MAX_MESSAGE_LENGTH = 500   # batas panjang karakter per pesan sebelum disimpan/dikirim ke API

# ---------------------------------------------------------------------------
# DOWNLOAD MUSIK (yt-dlp)
# ---------------------------------------------------------------------------
YTDLP_TIMEOUT = 180          # detik, download bisa lama tergantung koneksi
YTDLP_SEARCH_PREFIX = "ytsearch1:"   # ambil 1 hasil teratas saja

# ---------------------------------------------------------------------------
# TERMUX:API COMMAND TIMEOUT
# ---------------------------------------------------------------------------
TERMUX_API_TIMEOUT = 10   # detik, untuk termux-battery-status/tts/dll
MEDIA_PLAYER_TIMEOUT = 10
APP_LAUNCH_TIMEOUT = 10

# ---------------------------------------------------------------------------
# INPUT SUARA (opsional, butuh Termux:API)
# ---------------------------------------------------------------------------
# Jika True DAN command 'termux-speech-to-text' tersedia, assistant akan
# otomatis memakai microphone (speech recognizer bawaan Android) alih-alih
# menunggu ketikan setiap kali start. Bisa dimatikan/dihidupkan lagi kapan
# saja saat runtime dengan mengetik "mode ketik" atau "mode suara".
VOICE_INPUT_ENABLED = False

# Timeout (detik) menunggu proses termux-speech-to-text selesai. Dialog
# speech recognizer Android biasanya berhenti sendiri kalau tidak ada
# suara, tapi ini jaring pengaman supaya subprocess tidak nyantol
# selamanya kalau ada masalah (mis. dialog tertutup tanpa hasil).
VOICE_INPUT_TIMEOUT = 20

# ---------------------------------------------------------------------------
# BATTERY MONITOR
# ---------------------------------------------------------------------------
# Interval "efektif" job scheduler (HANYA untuk dokumentasi/README, bukan
# untuk polling di dalam Python). Pendaftaran job dilakukan lewat
# termux-job-scheduler, lihat setup.sh / instruksi pemasangan job.
BATTERY_JOB_PERIOD_MS = 30 * 60 * 1000   # 30 menit

# TTS normal (saat charging < 100%) hanya diucapkan jika persentase
# berubah minimal sekian persen sejak TTS terakhir, supaya tidak spam
# setiap kali scheduler jalan.
NORMAL_TTS_MIN_PERCENT_CHANGE = 10

# ---------------------------------------------------------------------------
# EMERGENCY MODE (baterai 100% dan masih charging)
# ---------------------------------------------------------------------------
EMERGENCY_CONFIRM_DELAY_SEC = 5     # jeda sebelum baca ulang untuk konfirmasi 100%
EMERGENCY_TTS_INTERVAL_SEC = 60     # ucapkan peringatan setiap 1 menit
EMERGENCY_MAX_DURATION_SEC = 60 * 60  # safety cap: mode darurat maksimal 1 jam
                                       # (proteksi kalau user lupa cabut charger
                                       # atau ada error yang bikin loop tidak
                                       # pernah mendeteksi status DISCHARGING)

# TTS balasan assistant
TTS_REPLY_ENABLED = True
TTS_MAX_CHARS = 300
