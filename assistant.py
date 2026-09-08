#!/data/data/com.termux/files/usr/bin/env python3
"""
assistant.py
============
Hybrid AI Personal Assistant untuk Termux (Android).

Prioritas command (WAJIB diikuti, lihat fungsi `handle_input`):
    1. STOP / EXIT
    2. LOCAL APP COMMAND   (buka <app>)
    3. LOCAL MUSIC COMMAND (putar musik <query>)
    4. BATTERY/DEVICE COMMAND
    5. OTHER LOCAL COMMAND
    6. ONLINE LLM
    7. OFFLINE FALLBACK

Desain difokuskan untuk RAM rendah (target < 50 MB saat idle/chat biasa):
    - Tidak ada library berat (numpy/pandas/torch/tensorflow/opencv).
    - Tidak membaca file musik ke RAM (hanya path yang diproses).
    - Memory percakapan dibatasi 10 pesan dan disimpan ke disk, bukan
      ditumpuk di RAM.
    - Semua subprocess punya timeout dan except spesifik (tidak pernah
      `except: pass` polos).
"""

import difflib
import glob
import json
import logging
import logging.handlers
import os
import re
import shutil
import socket
import subprocess
import sys
import urllib.error
import urllib.request

import config

# ---------------------------------------------------------------------------
# LOGGING
# ---------------------------------------------------------------------------

def setup_logging() -> logging.Logger:
    """
    Siapkan logger dengan rotating file handler supaya file log tidak
    tumbuh tanpa batas (sesuai batasan RAM/storage di spesifikasi).
    """
    os.makedirs(config.LOG_DIR, exist_ok=True)
    logger = logging.getLogger("hybrid_assistant")
    logger.setLevel(logging.INFO)

    if not logger.handlers:
        handler = logging.handlers.RotatingFileHandler(
            config.LOG_FILE,
            maxBytes=config.LOG_MAX_BYTES,
            backupCount=config.LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
        formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(message)s"
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    return logger


log = setup_logging()


# ---------------------------------------------------------------------------
# 1. DETEKSI ONLINE/OFFLINE
# ---------------------------------------------------------------------------

def is_online() -> bool:
    """
    Cek koneksi internet memakai TCP socket ringan (bukan ping/ICMP,
    karena ICMP sering diblokir operator/firewall).

    Timeout pendek (lihat config.ONLINE_CHECK_TIMEOUT) dan TIDAK retry
    tanpa batas -- kalau semua host gagal, anggap saja offline dan
    lanjutkan program (tidak boleh crash).
    """
    for host, port in config.ONLINE_CHECK_HOSTS:
        try:
            with socket.create_connection(
                (host, port), timeout=config.ONLINE_CHECK_TIMEOUT
            ):
                return True
        except OSError as exc:
            log.info("Cek online ke %s:%s gagal: %s", host, port, exc)
            continue
    return False


def voice_input_available() -> bool:
    return shutil.which("termux-speech-to-text") is not None


def listen_voice() -> str:
    """
    Rekam suara & transkripsi lewat termux-speech-to-text (bagian dari
    Termux:API) -- ini membuka speech recognizer bawaan Android, user
    bicara, hasilnya dikembalikan sebagai teks lewat stdout.

    Mengembalikan string kosong "" kalau gagal/dibatalkan/timeout/tidak
    tersedia -- TIDAK PERNAH melempar exception ke pemanggil. Pemanggil
    (main loop) yang menentukan fallback ke keyboard kalau hasilnya
    kosong.
    """
    if not voice_input_available():
        return ""

    try:
        result = subprocess.run(
            ["termux-speech-to-text"],
            capture_output=True,
            text=True,
            timeout=config.VOICE_INPUT_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        log.warning("Timeout menunggu input suara (termux-speech-to-text).")
        return ""
    except FileNotFoundError:
        log.error("termux-speech-to-text tidak ditemukan saat eksekusi.")
        return ""
    except Exception as exc:  # noqa: BLE001
        log.error("Error saat merekam suara: %s", exc)
        return ""

    if result.returncode != 0:
        log.warning(
            "termux-speech-to-text gagal: %s", result.stderr.strip()
        )
        return ""

    return result.stdout.strip()


# ---------------------------------------------------------------------------
# 2. LOCAL APP COMMAND
# ---------------------------------------------------------------------------

def open_app(app_name: str) -> str:
    """
    Buka aplikasi lokal berdasarkan nama alias di config.APP_PACKAGES.

    Menggunakan `monkey -p <package> -c android.intent.category.LAUNCHER 1`
    lewat subprocess karena tidak memerlukan root dan tidak perlu tahu
    nama activity utama aplikasi (cukup package name).

    Tidak pernah crash: package tidak ditemukan / monkey gagal / timeout
    semuanya ditangani dan dikembalikan sebagai pesan error yang jelas.
    """
    package = config.APP_PACKAGES.get(app_name.lower())
    if not package:
        return (
            f"Package untuk '{app_name}' belum terdaftar di config.py "
            f"(APP_PACKAGES). Cek dulu package yang benar-benar terpasang "
            f"dengan: pm list packages | grep -i {app_name}"
        )

    command = [
        "monkey",
        "-p", package,
        "-c", "android.intent.category.LAUNCHER",
        "1",
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=config.APP_LAUNCH_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        log.warning("Timeout saat membuka app %s (%s)", app_name, package)
        return f"Timeout saat mencoba membuka {app_name}."
    except FileNotFoundError:
        log.error("Command 'monkey' tidak ditemukan di PATH.")
        return (
            "Command 'monkey' tidak ditemukan. Pastikan kamu menjalankan "
            "assistant ini di dalam Termux (bukan Python biasa)."
        )
    except Exception as exc:  # noqa: BLE001 - tetap dilog, bukan silent
        log.error("Error tak terduga saat membuka %s: %s", app_name, exc)
        return f"Gagal membuka {app_name}: {exc}"

    if result.returncode != 0:
        log.warning(
            "monkey exit code %s untuk %s: %s",
            result.returncode, package, result.stderr.strip(),
        )
        return (
            f"Tidak bisa membuka {app_name} (package: {package}). "
            f"Kemungkinan package tidak terpasang atau nama package salah. "
            f"Cek manual dengan: monkey -p {package} "
            f"-c android.intent.category.LAUNCHER 1"
        )

    return f"Membuka {app_name}..."


# ---------------------------------------------------------------------------
# 3. LOCAL MUSIC PLAYER
# ---------------------------------------------------------------------------

def normalize_music_text(text: str) -> str:
    """
    Normalisasi teks untuk pencarian musik: lowercase, ganti separator
    umum nama file (underscore, dash, titik) jadi spasi, lalu rapikan
    spasi ganda. Ini membuat "Bohemian_Rhapsody.mp3" bisa cocok dengan
    query "bohemian rhapsody" walau nama file pakai underscore.
    """
    text = text.lower()
    text = re.sub(r"[_\-.]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def score_music_match(query_norm: str, query_words: list, name_norm: str) -> float:
    """
    Hitung skor kecocokan (semakin tinggi semakin relevan, 0 = tidak
    cocok sama sekali):
      - Substring utuh cocok        -> skor > 1.0 (prioritas tertinggi,
                                        makin panjang query relatif ke
                                        nama file makin tinggi skornya)
      - Sebagian/semua kata cocok   -> skor 0.0-1.0 (rasio kata yang
                                        ditemukan di nama file)
      - Tidak ada kata yang cocok   -> fallback fuzzy match (difflib)
                                        untuk toleransi typo ringan;
                                        di bawah ambang batas dianggap
                                        tidak cocok (skor 0.0)
    """
    if not query_words:
        return 0.0

    if query_norm in name_norm:
        return 1.0 + (len(query_norm) / max(len(name_norm), 1))

    words_found = sum(1 for word in query_words if word in name_norm)
    word_ratio = words_found / len(query_words)
    if word_ratio > 0:
        return word_ratio

    fuzzy_ratio = difflib.SequenceMatcher(None, query_norm, name_norm).ratio()
    if fuzzy_ratio >= config.MUSIC_FUZZY_MATCH_THRESHOLD:
        return fuzzy_ratio
    return 0.0


def find_local_music(query: str):
    """
    Cari file musik di config.MUSIC_DIR memakai os.walk (standard
    library saja, tidak membaca isi file ke RAM -- hanya mencocokkan
    nama file).

    Pencarian tidak lagi hanya substring persis: nama file dinormalisasi
    (underscore/dash -> spasi) dan dicocokkan per-kata, plus fallback
    fuzzy match untuk typo ringan. Hasil diurutkan dari yang paling
    relevan (skor tertinggi duluan) supaya handle_music_request() yang
    mengambil hasil pertama (matches[0]) mendapat lagu paling cocok,
    bukan sekadar yang pertama ditemukan os.walk.
    """
    query_norm = normalize_music_text(query)
    query_words = query_norm.split()
    scored_matches = []

    if not os.path.isdir(config.MUSIC_DIR):
        log.warning("Folder musik tidak ditemukan: %s", config.MUSIC_DIR)
        return []

    for root, _dirs, files in os.walk(config.MUSIC_DIR):
        for filename in files:
            if not filename.lower().endswith(config.SUPPORTED_MUSIC_EXT):
                continue
            name_no_ext = os.path.splitext(filename)[0]
            name_norm = normalize_music_text(name_no_ext)
            score = score_music_match(query_norm, query_words, name_norm)
            if score > 0:
                scored_matches.append((score, os.path.join(root, filename)))

    scored_matches.sort(key=lambda item: item[0], reverse=True)
    return [path for _score, path in scored_matches]


def media_player_available() -> bool:
    return shutil.which("termux-media-player") is not None


def play_music_file(path: str) -> str:
    """
    Putar file musik lewat termux-media-player. Selalu cek dulu apakah
    command tersedia sebelum dipanggil.
    """
    if not media_player_available():
        return (
            "Command 'termux-media-player' tidak ditemukan.\n"
            "Install dulu Termux:API:\n"
            "  1. Install aplikasi Termux:API dari F-Droid/Play Store.\n"
            "  2. Jalankan: pkg install termux-api"
        )

    try:
        result = subprocess.run(
            ["termux-media-player", "play", path],
            capture_output=True,
            text=True,
            timeout=config.MEDIA_PLAYER_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        log.warning("Timeout saat memutar musik: %s", path)
        return "Timeout saat mencoba memutar musik."
    except FileNotFoundError:
        log.error("termux-media-player tidak ditemukan saat eksekusi.")
        return "termux-media-player tidak ditemukan."
    except Exception as exc:  # noqa: BLE001
        log.error("Error saat memutar musik %s: %s", path, exc)
        return f"Gagal memutar musik: {exc}"

    if result.returncode != 0:
        log.warning("termux-media-player gagal: %s", result.stderr.strip())
        return f"Gagal memutar file: {os.path.basename(path)}"

    return f"Memutar: {os.path.basename(path)}"


def control_music_player(action: str) -> str:
    """
    Kontrol playback musik yang sedang berjalan lewat termux-media-player.
    action harus salah satu dari: "play" (resume), "pause", "stop" --
    ini persis subcommand yang dikenali termux-media-player sendiri.
    """
    if not media_player_available():
        return (
            "Command 'termux-media-player' tidak ditemukan. "
            "Install dulu Termux:API (pkg install termux-api)."
        )

    try:
        result = subprocess.run(
            ["termux-media-player", action],
            capture_output=True,
            text=True,
            timeout=config.MEDIA_PLAYER_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        log.warning("Timeout saat menjalankan termux-media-player %s", action)
        return f"Timeout saat mencoba '{action}' musik."
    except FileNotFoundError:
        log.error("termux-media-player tidak ditemukan saat eksekusi.")
        return "termux-media-player tidak ditemukan."
    except Exception as exc:  # noqa: BLE001
        log.error("Error saat kontrol musik (%s): %s", action, exc)
        return f"Gagal menjalankan '{action}': {exc}"

    if result.returncode != 0:
        log.warning(
            "termux-media-player %s gagal: %s", action, result.stderr.strip()
        )
        return f"Gagal menjalankan '{action}': {result.stderr.strip()}"

    label = {
        "pause": "Musik dijeda.",
        "play": "Melanjutkan musik.",
        "stop": "Musik dihentikan.",
    }
    return label.get(action, f"Perintah '{action}' dijalankan.")


# ---------------------------------------------------------------------------
# 4. AUTO DOWNLOAD MUSIK (yt-dlp) -- dipanggil hanya jika lokal tidak ada
# ---------------------------------------------------------------------------

def ytdlp_available() -> bool:
    return shutil.which("yt-dlp") is not None


def download_music(query: str) -> str:
    """
    Download 1 hasil pencarian teratas via yt-dlp, konversi ke mp3,
    simpan ke config.MUSIC_DIR, lalu putar.

    Hanya berjalan jika online (dicek oleh pemanggil). Tidak melakukan
    download paralel -- satu proses subprocess sinkron per permintaan.

    PENTING (batasan legal/etis): ini hanya memanggil yt-dlp terhadap
    sumber yang memang didukung yt-dlp. Tidak ada usaha bypass DRM,
    proteksi login, atau paywall.
    """
    if not ytdlp_available():
        return (
            "yt-dlp tidak ditemukan. Install dengan:\n"
            "  pip install yt-dlp"
        )

    os.makedirs(config.MUSIC_DIR, exist_ok=True)
    search_target = f"{config.YTDLP_SEARCH_PREFIX}{query}"
    output_template = os.path.join(config.MUSIC_DIR, "%(title)s.%(ext)s")

    command = [
        "yt-dlp",
        "--no-playlist",
        "-x",
        "--audio-format", "mp3",
        "--output", output_template,
        search_target,
    ]

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=config.YTDLP_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        log.warning("Timeout saat download musik: %s", query)
        return "Download musik timeout. Coba lagi nanti atau cek koneksi."
    except FileNotFoundError:
        log.error("yt-dlp tidak ditemukan saat eksekusi.")
        return "yt-dlp tidak ditemukan."
    except Exception as exc:  # noqa: BLE001
        log.error("Error saat download musik %s: %s", query, exc)
        return f"Gagal download musik: {exc}"

    if result.returncode != 0:
        log.warning("yt-dlp gagal: %s", result.stderr.strip()[-500:])
        return f"Musik '{query}' tidak ditemukan atau gagal diunduh."

    # Cari file mp3 yang paling baru dimodifikasi sebagai hasil download.
    mp3_files = glob.glob(os.path.join(config.MUSIC_DIR, "*.mp3"))
    if not mp3_files:
        return "Download selesai tapi file tidak ditemukan di folder musik."

    newest_file = max(mp3_files, key=os.path.getmtime)
    play_result = play_music_file(newest_file)
    return f"Berhasil download '{query}'. {play_result}"


def handle_music_request(query: str, online: bool) -> str:
    matches = find_local_music(query)
    if matches:
        return play_music_file(matches[0])

    if not online:
        return f"Musik '{query}' tidak tersedia secara lokal (dan sedang offline)."

    return download_music(query)


# ---------------------------------------------------------------------------
# BATTERY / DEVICE COMMAND (ringan, hanya baca status sekali)
# ---------------------------------------------------------------------------

def get_battery_status_once():
    """
    Baca status baterai sekali saja (dipakai untuk command interaktif
    "cek baterai", BUKAN untuk polling terus-menerus).
    """
    try:
        result = subprocess.run(
            ["termux-battery-status"],
            capture_output=True,
            text=True,
            timeout=config.TERMUX_API_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return None, "Timeout saat membaca status baterai."
    except FileNotFoundError:
        return None, "termux-battery-status tidak ditemukan (perlu Termux:API)."
    except Exception as exc:  # noqa: BLE001
        return None, f"Gagal membaca status baterai: {exc}"

    try:
        data = json.loads(result.stdout)
    except (json.JSONDecodeError, TypeError):
        return None, "Output status baterai tidak valid."

    return data, None


def handle_battery_command() -> str:
    data, error = get_battery_status_once()
    if error:
        return error
    percentage = data.get("percentage", "?")
    status = data.get("status", "UNKNOWN")
    return f"Baterai: {percentage}% ({status})"


# ---------------------------------------------------------------------------
# 6. CONVERSATION MEMORY
# ---------------------------------------------------------------------------

def load_memory():
    """
    Muat memory dari disk. Kalau file tidak ada atau JSON corrupt,
    reset ke memory kosong dan lanjutkan (tidak boleh crash).
    """
    if not os.path.exists(config.MEMORY_FILE):
        return []

    try:
        with open(config.MEMORY_FILE, "r", encoding="utf-8") as file_handle:
            data = json.load(file_handle)
        if not isinstance(data, list):
            raise ValueError("Format memory tidak sesuai (bukan list).")
        return data
    except (json.JSONDecodeError, ValueError, OSError) as exc:
        log.warning("memory.json corrupt/gagal dibaca, reset. Detail: %s", exc)
        return []


def sanitize_message(text: str) -> str:
    """Potong panjang pesan sebelum disimpan/dikirim ke API."""
    text = text.strip()
    if len(text) > config.MAX_MESSAGE_LENGTH:
        text = text[: config.MAX_MESSAGE_LENGTH]
    return text


def save_memory(memory: list) -> None:
    """
    Simpan memory ke disk, dipotong maksimal config.MEMORY_LIMIT pesan
    terakhir. Tidak pernah menyimpan API key / data binary -- karena
    hanya field role & content (string pendek) yang pernah dimasukkan
    ke list ini.
    """
    trimmed = memory[-config.MEMORY_LIMIT:]
    try:
        with open(config.MEMORY_FILE, "w", encoding="utf-8") as file_handle:
            json.dump(trimmed, file_handle, ensure_ascii=False)
    except OSError as exc:
        log.error("Gagal menyimpan memory.json: %s", exc)


def append_message(memory: list, role: str, content: str) -> list:
    memory.append({"role": role, "content": sanitize_message(content)})
    memory = memory[-config.MEMORY_LIMIT:]
    save_memory(memory)
    return memory


# ---------------------------------------------------------------------------
# 4/5. ONLINE LLM SYSTEM
# ---------------------------------------------------------------------------

class LLMProvider:
    def chat(self, messages: list) -> str:
        raise NotImplementedError


class GroqProvider(LLMProvider):
    """
    Groq menyediakan endpoint chat completion yang kompatibel dengan
    format OpenAI (POST JSON, header Authorization: Bearer <key>).
    """

    ENDPOINT = "https://api.groq.com/openai/v1/chat/completions"

    def __init__(self, api_key: str, model: str):
        self.api_key = api_key
        self.model = model

    def chat(self, messages: list) -> str:
        payload = json.dumps({
            "model": self.model,
            "messages": messages,
        }).encode("utf-8")

        request = urllib.request.Request(
            self.ENDPOINT,
            data=payload,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
        )
        with urllib.request.urlopen(
            request, timeout=config.LLM_REQUEST_TIMEOUT
        ) as response:
            body = json.loads(response.read().decode("utf-8"))

        return body["choices"][0]["message"]["content"].strip()


class GeminiProvider(LLMProvider):
    """
    Gemini generateContent endpoint. API key dikirim sebagai query
    parameter sesuai dokumentasi resmi Google AI Studio.
    """

    def __init__(self, api_key: str, model: str):
        self.api_key = api_key
        self.model = model

    def chat(self, messages: list) -> str:
        # Gemini tidak memakai format role user/assistant OpenAI-style
        # secara langsung untuk endpoint sederhana ini, jadi gabungkan
        # riwayat percakapan menjadi satu blok teks kontekstual.
        history_text = "\n".join(
            f"{m['role']}: {m['content']}" for m in messages
        )

        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.model}:generateContent?key={self.api_key}"
        )
        payload = json.dumps({
            "contents": [{"parts": [{"text": history_text}]}]
        }).encode("utf-8")

        request = urllib.request.Request(
            url,
            data=payload,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(
            request, timeout=config.LLM_REQUEST_TIMEOUT
        ) as response:
            body = json.loads(response.read().decode("utf-8"))

        return body["candidates"][0]["content"]["parts"][0]["text"].strip()


def build_provider(name: str):
    """
    Bangun instance provider dari nama. Mengembalikan None (bukan
    exception) kalau API key tidak ada, supaya pemanggil bisa fallback
    dengan aman.
    """
    if name == "groq":
        api_key = os.environ.get(config.GROQ_API_KEY_ENV)
        if not api_key:
            return None
        return GroqProvider(api_key, config.GROQ_MODEL)

    if name == "gemini":
        api_key = os.environ.get(config.GEMINI_API_KEY_ENV)
        if not api_key:
            return None
        return GeminiProvider(api_key, config.GEMINI_MODEL)

    return None


def call_llm(messages: list) -> str:
    """
    Panggil provider utama (config.LLM_PROVIDER). Kalau gagal (API
    error/key kosong/timeout), coba fallback ke provider lain SEKALI
    saja -- tidak retry tanpa batas.
    """
    provider_order = [config.LLM_PROVIDER]
    for other in ("groq", "gemini"):
        if other not in provider_order:
            provider_order.append(other)

    last_error = None
    for provider_name in provider_order:
        provider = build_provider(provider_name)
        if provider is None:
            continue
        try:
            return provider.chat(messages)
        except urllib.error.HTTPError as exc:
            last_error = f"{provider_name} HTTP error {exc.code}"
            log.warning(last_error)
        except urllib.error.URLError as exc:
            last_error = f"{provider_name} koneksi gagal: {exc.reason}"
            log.warning(last_error)
        except (KeyError, json.JSONDecodeError, IndexError) as exc:
            last_error = f"{provider_name} respons tidak dikenali: {exc}"
            log.warning(last_error)
        except Exception as exc:  # noqa: BLE001
            last_error = f"{provider_name} error tak terduga: {exc}"
            log.error(last_error)

    return (
        "Maaf, LLM sedang tidak bisa diakses "
        f"({last_error or 'tidak ada API key yang di-set'}). "
        "Perintah lokal tetap bisa dipakai."
    )


# ---------------------------------------------------------------------------
# 2/9. PARSER PERINTAH LOKAL + PRIORITAS
# ---------------------------------------------------------------------------

STOP_WORDS = {"exit", "quit", "keluar"}


def parse_open_app(text: str):
    lowered = text.lower().strip()
    if lowered.startswith("buka "):
        return lowered[len("buka "):].strip()
    return None


MUSIC_PAUSE_COMMANDS = {"pause musik", "pause lagu", "jeda musik", "jeda lagu"}
MUSIC_RESUME_COMMANDS = {
    "lanjutkan musik", "lanjutkan lagu", "resume musik", "resume lagu",
    "lanjut musik", "lanjut lagu", "play musik", "play lagu",
}
MUSIC_STOP_COMMANDS = {
    "stop musik", "stop lagu", "berhenti musik", "berhenti lagu",
    "matikan musik", "matikan lagu", "hentikan musik", "hentikan lagu",
}


def parse_music_control(text: str):
    """
    Kenali perintah kontrol musik (bukan "putar lagu <judul>", tapi
    kontrol atas lagu yang SEDANG diputar). Mengembalikan action untuk
    control_music_player(), atau None kalau bukan perintah kontrol.
    """
    lowered = text.lower().strip()
    if lowered in MUSIC_PAUSE_COMMANDS:
        return "pause"
    if lowered in MUSIC_RESUME_COMMANDS:
        return "play"
    if lowered in MUSIC_STOP_COMMANDS:
        return "stop"
    return None


def parse_play_music(text: str):
    lowered = text.lower().strip()
    for prefix in ("putar musik ", "putar lagu "):
        if lowered.startswith(prefix):
            # Ambil query dari teks ASLI (bukan lowered) supaya nama
            # lagu tetap sesuai kapitalisasi user, pencarian tetap
            # case-insensitive di find_local_music().
            return text.strip()[len(prefix):].strip()
    return None


def is_battery_command(text: str) -> bool:
    lowered = text.lower().strip()
    return lowered in {"cek baterai", "battery", "status baterai"}


def handle_input(user_text: str, memory: list, online: bool) -> str:
    """
    Terapkan urutan prioritas sesuai spesifikasi:
      1. STOP/EXIT ditangani di main loop (bukan di sini).
      2. LOCAL APP COMMAND
      3. LOCAL MUSIC COMMAND
      4. BATTERY/DEVICE COMMAND
      5. (OTHER LOCAL COMMAND -- belum ada, tempat ekstensi ke depan)
      6. ONLINE LLM
      7. OFFLINE FALLBACK
    """
    app_name = parse_open_app(user_text)
    if app_name:
        return open_app(app_name)

    music_control = parse_music_control(user_text)
    if music_control:
        return control_music_player(music_control)

    music_query = parse_play_music(user_text)
    if music_query:
        return handle_music_request(music_query, online)

    if is_battery_command(user_text):
        return handle_battery_command()

    if online:
        messages = memory + [{"role": "user", "content": sanitize_message(user_text)}]
        return call_llm(messages)

    return "Sedang offline dan perintah tidak dikenali sebagai command lokal."


# ---------------------------------------------------------------------------
# MAIN LOOP INTERAKTIF
# ---------------------------------------------------------------------------

def main():
    print("Hybrid Assistant siap. Ketik 'exit' / 'quit' / 'keluar' untuk berhenti.")
    memory = load_memory()

    voice_mode = config.VOICE_INPUT_ENABLED and voice_input_available()
    if config.VOICE_INPUT_ENABLED and not voice_input_available():
        print(
            "(Mode suara aktif di config tapi 'termux-speech-to-text' tidak "
            "ditemukan -- pakai keyboard. Install Termux:API untuk "
            "mengaktifkan mode suara: pkg install termux-api, lalu pasang "
            "app Termux:API dari F-Droid/Play Store.)"
        )
    print("(Ketik 'mode ketik' atau 'mode suara' kapan saja untuk beralih input.)")

    while True:
        if voice_mode:
            print("🎤 Ucapkan perintah...")
            user_text = listen_voice().strip()
            if not user_text:
                print(
                    "Assistant: Tidak menangkap suara. Coba lagi, atau "
                    "ketik 'mode ketik' untuk beralih ke keyboard."
                )
                continue
            print(f"You (suara): {user_text}")
        else:
            try:
                user_text = input("You: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nAssistant: Sampai jumpa.")
                break

        if not user_text:
            continue

        lowered = user_text.lower()

        if lowered in STOP_WORDS:
            print("Assistant: Sampai jumpa.")
            break

        if lowered == "mode suara":
            if voice_input_available():
                voice_mode = True
                print("Assistant: Mode suara diaktifkan.")
            else:
                print(
                    "Assistant: 'termux-speech-to-text' tidak ditemukan, "
                    "tetap pakai keyboard."
                )
            continue

        if lowered in {"mode ketik", "mode teks"}:
            voice_mode = False
            print("Assistant: Mode ketik diaktifkan.")
            continue

        online = is_online()
        try:
            reply = handle_input(user_text, memory, online)
        except Exception as exc:  # noqa: BLE001 - jaring pengaman terakhir
            log.error("Error tak terduga di handle_input: %s", exc)
            reply = "Terjadi error internal, tapi assistant tidak crash."

        print(f"Assistant: {reply}")
        speak_reply(reply)

        memory = append_message(memory, "user", user_text)
        memory = append_message(memory, "assistant", reply)




def speak_reply(text: str) -> None:
    """Ucapkan balasan assistant lewat termux-tts-speak, tidak pernah crash."""
    if not getattr(config, "TTS_REPLY_ENABLED", False):
        return
    spoken_text = text[: getattr(config, "TTS_MAX_CHARS", 300)]
    try:
        subprocess.run(
            ["termux-tts-speak", spoken_text],
            capture_output=True,
            text=True,
            timeout=config.TERMUX_API_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        log.warning("Timeout saat TTS balasan.")
    except FileNotFoundError:
        log.error("termux-tts-speak tidak ditemukan.")
    except Exception as exc:
        log.error("Error tak terduga saat TTS balasan: %s", exc)

if __name__ == "__main__":
    sys.exit(main() or 0)
