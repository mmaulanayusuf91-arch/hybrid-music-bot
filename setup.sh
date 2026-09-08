#!/data/data/com.termux/files/usr/bin/bash
#
# setup.sh
# ========
# Setup environment Termux untuk Hybrid Assistant.
#
# CATATAN PENTING SEBELUM MENJALANKAN:
# 1. "pkg install termux-api" HANYA memasang command-line tools-nya.
#    Kamu WAJIB juga menginstall APLIKASI Android terpisah bernama
#    "Termux:API" (dari F-Droid atau Play Store, sumber yang SAMA
#    dengan sumber Termux utama kamu -- F-Droid dengan F-Droid, jangan
#    dicampur dengan versi Play Store, karena signature APK berbeda
#    bisa menyebabkan komunikasi antar-app gagal).
# 2. Script ini tidak menjamin semua command Termux:API berfungsi kalau
#    APK Termux dan Termux:API berasal dari sumber build yang berbeda.
#
# Jalankan dengan: bash setup.sh

set -e

echo ">> Update & upgrade package Termux..."
pkg update -y
pkg upgrade -y

echo ">> Install Python..."
pkg install -y python

echo ">> Install termux-api (CLI tools)..."
pkg install -y termux-api

echo ">> Install ffmpeg (dibutuhkan yt-dlp untuk konversi audio)..."
pkg install -y ffmpeg

echo ">> Install yt-dlp lewat pip..."
pip install --upgrade pip
pip install yt-dlp

echo ">> Minta izin akses storage (untuk folder musik publik, opsional)..."
echo "   Jika muncul dialog permission Android, tekan Allow."
termux-setup-storage || echo "   (Lewati jika sudah pernah di-setup sebelumnya.)"

echo ">> Membuat struktur folder project (kalau belum ada)..."
mkdir -p hybrid_assistant/logs
mkdir -p hybrid_assistant/music

cat <<'EOF'

=====================================================================
SETUP SELESAI (bagian command-line).

LANGKAH MANUAL YANG WAJIB DILAKUKAN:

1. Install aplikasi "Termux:API" dari toko aplikasi yang SAMA dengan
   sumber Termux kamu (F-Droid <-> F-Droid, atau varian Play Store
   yang saling kompatibel).

2. Set API key LLM sebagai environment variable (JANGAN taruh di
   source code). Contoh, tambahkan ke ~/.bashrc:

       export GROQ_API_KEY="isi-api-key-groq-kamu"
       export GEMINI_API_KEY="isi-api-key-gemini-kamu"

   lalu jalankan:  source ~/.bashrc

3. Cek nama package aplikasi yang mau dibuka assistant, sesuaikan
   config.py -> APP_PACKAGES:

       pm list packages | grep -i nama_app

4. Tes command Termux:API dasar untuk memastikan semuanya terhubung:

       termux-battery-status
       termux-tts-speak "tes suara"
       termux-media-player info

5. Jalankan assistant:

       cd hybrid_assistant
       python assistant.py

Lihat instruksi terpisah untuk mendaftarkan battery_monitor.py ke
termux-job-scheduler.
=====================================================================
EOF
