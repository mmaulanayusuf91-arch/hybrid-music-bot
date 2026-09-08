#!/data/data/com.termux/files/usr/bin/env python3
"""
battery_monitor.py
===================
Dipanggil oleh `termux-job-scheduler` setiap 30 menit (lihat instruksi
pendaftaran job di README/jawaban chat). Script ini TIDAK melakukan
polling terus-menerus di kondisi normal -- baca status sekali, putuskan
aksi, lalu keluar.

PENGECUALIAN: kondisi "emergency" (baterai 100% dan masih charging).
Spesifikasi asli meminta TTS setiap 1 menit selama charger belum
dicabut. Android JobScheduler (dasar dari termux-job-scheduler) TIDAK
menjamin job periodik berjalan lebih cepat dari ~15 menit, jadi
mustahil mengandalkan job scheduler untuk interval 1 menit yang andal.

TRADE-OFF yang dipilih (dijelaskan juga di jawaban utama):
    Saat kondisi 100%+CHARGING benar-benar terkonfirmasi, script ini
    masuk ke loop tertutup (run_emergency_loop) yang:
      - memegang termux-wake-lock supaya proses tidak dibunuh OOM
        killer saat layar mati,
      - TTS setiap EMERGENCY_TTS_INTERVAL_SEC (60 detik),
      - dibatasi durasi maksimum EMERGENCY_MAX_DURATION_SEC (safety cap)
        supaya wake-lock TIDAK PERNAH aktif selamanya walau ada bug,
      - SELALU memanggil termux-wake-unlock di blok `finally`, bahkan
        kalau terjadi exception tak terduga.
    Konsekuensinya: selama emergency mode aktif, ada satu proses Python
    yang hidup lebih lama dari biasanya (bukan "keluar sesingkat
    mungkin" seperti mode normal). Ini disengaja dan dianggap lebih
    aman daripada mencoba memaksa job scheduler berjalan tiap menit
    (yang tidak dijamin Android) atau meninggalkan wake-lock menyala
    tanpa mekanisme pelepasan otomatis.
"""

import json
import logging
import logging.handlers
import os
import subprocess
import time

import config

# ---------------------------------------------------------------------------
# LOGGING (pakai file log yang sama dengan assistant.py, rotating)
# ---------------------------------------------------------------------------

def setup_logging() -> logging.Logger:
    os.makedirs(config.LOG_DIR, exist_ok=True)
    logger = logging.getLogger("battery_monitor")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        handler = logging.handlers.RotatingFileHandler(
            config.LOG_FILE,
            maxBytes=config.LOG_MAX_BYTES,
            backupCount=config.LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
        formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    return logger


log = setup_logging()


# ---------------------------------------------------------------------------
# STATE PERSISTENCE (battery_state.json)
# ---------------------------------------------------------------------------

DEFAULT_STATE = {
    "last_percentage": None,
    "last_status": None,
    "last_tts_percentage": None,
    "emergency_mode": False,
    "emergency_start_time": None,
}


def load_state() -> dict:
    if not os.path.exists(config.BATTERY_STATE_FILE):
        return dict(DEFAULT_STATE)
    try:
        with open(config.BATTERY_STATE_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            raise ValueError("battery_state.json bukan objek JSON.")
        merged = dict(DEFAULT_STATE)
        merged.update(data)
        return merged
    except (json.JSONDecodeError, ValueError, OSError) as exc:
        log.warning("battery_state.json corrupt, reset ke default: %s", exc)
        return dict(DEFAULT_STATE)


def save_state(state: dict) -> None:
    try:
        with open(config.BATTERY_STATE_FILE, "w", encoding="utf-8") as fh:
            json.dump(state, fh)
    except OSError as exc:
        log.error("Gagal menyimpan battery_state.json: %s", exc)


# ---------------------------------------------------------------------------
# TERMUX:API WRAPPERS (semua try/except + timeout, tidak pernah crash)
# ---------------------------------------------------------------------------

def get_battery_status():
    """
    Mengembalikan (dict_status, error_message).
    dict_status berisi minimal 'percentage' dan 'status' kalau sukses.
    """
    try:
        result = subprocess.run(
            ["termux-battery-status"],
            capture_output=True,
            text=True,
            timeout=config.TERMUX_API_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return None, "Timeout membaca termux-battery-status."
    except FileNotFoundError:
        return None, "termux-battery-status tidak ditemukan (Termux:API belum terpasang)."
    except Exception as exc:  # noqa: BLE001
        return None, f"Error tak terduga membaca status baterai: {exc}"

    try:
        data = json.loads(result.stdout)
    except (json.JSONDecodeError, TypeError) as exc:
        return None, f"Output battery-status tidak valid: {exc}"

    if "percentage" not in data or "status" not in data:
        return None, "Field percentage/status tidak ada di output."

    return data, None


def speak(text: str) -> None:
    try:
        subprocess.run(
            ["termux-tts-speak", text],
            capture_output=True,
            text=True,
            timeout=config.TERMUX_API_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        log.warning("Timeout saat TTS: %s", text)
    except FileNotFoundError:
        log.error("termux-tts-speak tidak ditemukan.")
    except Exception as exc:  # noqa: BLE001
        log.error("Error tak terduga saat TTS: %s", exc)


def wake_lock() -> bool:
    try:
        subprocess.run(
            ["termux-wake-lock"],
            capture_output=True,
            text=True,
            timeout=config.TERMUX_API_TIMEOUT,
        )
        return True
    except subprocess.TimeoutExpired:
        log.error("Timeout saat termux-wake-lock.")
    except FileNotFoundError:
        log.error("termux-wake-lock tidak ditemukan.")
    except Exception as exc:  # noqa: BLE001
        log.error("Error tak terduga saat wake-lock: %s", exc)
    return False


def wake_unlock() -> None:
    try:
        subprocess.run(
            ["termux-wake-unlock"],
            capture_output=True,
            text=True,
            timeout=config.TERMUX_API_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        log.error("Timeout saat termux-wake-unlock.")
    except FileNotFoundError:
        log.error("termux-wake-unlock tidak ditemukan.")
    except Exception as exc:  # noqa: BLE001
        log.error("Error tak terduga saat wake-unlock: %s", exc)


# ---------------------------------------------------------------------------
# KONFIRMASI 100% + CHARGING (sensor HP clone bisa delay/tidak akurat)
# ---------------------------------------------------------------------------

def confirm_full_charge() -> bool:
    """
    Baca ulang status setelah jeda singkat. Hanya dianggap valid kalau
    bacaan kedua JUGA menunjukkan 100% + CHARGING. Ini mengurangi
    kemungkinan false trigger dari sensor yang delay/tidak stabil.
    """
    time.sleep(config.EMERGENCY_CONFIRM_DELAY_SEC)
    data, error = get_battery_status()
    if error:
        log.warning("Gagal konfirmasi ulang baterai penuh: %s", error)
        return False
    return data.get("percentage") == 100 and data.get("status") == "CHARGING"


# ---------------------------------------------------------------------------
# EMERGENCY MODE
# ---------------------------------------------------------------------------

def run_emergency_loop(state: dict) -> None:
    """
    Loop tertutup dan dibatasi waktu. WAJIB selalu melepas wake-lock di
    blok finally, apa pun yang terjadi (termasuk exception tak
    terduga), supaya wake-lock TIDAK PERNAH menyala selamanya.
    """
    if not state.get("emergency_start_time"):
        state["emergency_start_time"] = time.time()

    state["emergency_mode"] = True
    save_state(state)

    lock_ok = wake_lock()
    if not lock_ok:
        log.error("Gagal mengaktifkan wake-lock, emergency mode tetap lanjut tanpa lock.")

    try:
        speak("Charger sudah penuh. Silakan cabut charger.")

        while True:
            elapsed = time.time() - state["emergency_start_time"]
            if elapsed >= config.EMERGENCY_MAX_DURATION_SEC:
                log.warning(
                    "Emergency mode mencapai batas waktu maksimum (%ss), "
                    "keluar paksa demi keamanan wake-lock.",
                    config.EMERGENCY_MAX_DURATION_SEC,
                )
                break

            time.sleep(config.EMERGENCY_TTS_INTERVAL_SEC)

            data, error = get_battery_status()
            if error:
                log.warning("Gagal membaca status saat emergency loop: %s", error)
                # Jangan langsung keluar karena satu bacaan gagal -- lanjut
                # loop, tapi tetap terikat batas waktu maksimum di atas.
                continue

            if data.get("status") == "DISCHARGING":
                speak("Terima kasih, charger sudah dicabut.")
                log.info("Charger dicabut, keluar dari emergency mode.")
                break

            speak("Charger sudah penuh. Silakan cabut charger.")

    finally:
        wake_unlock()
        state["emergency_mode"] = False
        state["emergency_start_time"] = None
        save_state(state)


# ---------------------------------------------------------------------------
# MODE NORMAL (charging < 100%, TTS tidak spam)
# ---------------------------------------------------------------------------

def handle_normal_charging(state: dict, percentage: int) -> None:
    last_tts_percentage = state.get("last_tts_percentage")
    should_speak = (
        last_tts_percentage is None
        or abs(percentage - last_tts_percentage) >= config.NORMAL_TTS_MIN_PERCENT_CHANGE
    )
    if should_speak:
        speak(f"Baterai {percentage} persen, sedang mengisi daya.")
        state["last_tts_percentage"] = percentage


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

def main():
    state = load_state()

    data, error = get_battery_status()
    if error:
        log.error("battery_monitor berhenti tanpa aksi: %s", error)
        return

    percentage = data.get("percentage")
    status = data.get("status", "UNKNOWN")
    log.info("Baca status baterai: %s%% (%s)", percentage, status)

    # --- Self-healing: kalau invocation SEBELUMNYA sempat masuk
    # emergency_mode tapi prosesnya mati (Termux dibunuh sistem dsb),
    # jangan biarkan wake-lock nyangkut selamanya. Lanjutkan/selesaikan
    # di invocation ini.
    if state.get("emergency_mode"):
        if status == "DISCHARGING":
            speak("Terima kasih, charger sudah dicabut.")
            wake_unlock()
            state["emergency_mode"] = False
            state["emergency_start_time"] = None
            save_state(state)
        else:
            run_emergency_loop(state)
        state["last_percentage"] = percentage
        state["last_status"] = status
        save_state(state)
        return

    if percentage == 100 and status == "CHARGING":
        if confirm_full_charge():
            run_emergency_loop(state)
        else:
            log.info("Baterai 100%%+CHARGING tidak terkonfirmasi ulang, dianggap sensor glitch.")
    elif status == "CHARGING" and isinstance(percentage, int) and percentage < 100:
        handle_normal_charging(state, percentage)
    elif status == "DISCHARGING":
        # reset penanda TTS supaya siklus charging berikutnya mulai bersih
        state["last_tts_percentage"] = None

    state["last_percentage"] = percentage
    state["last_status"] = status
    save_state(state)


if __name__ == "__main__":
    main()
