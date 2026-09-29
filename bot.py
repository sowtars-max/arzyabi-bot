#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🛠️ ربات مدیریت کانال Arzyabi EAM
=============================
ربات فقط و فقط با صاحب کانال صحبت می‌کند.
مستندات کامل: README-FA.md

متغیرهای محیطی:
  BOT_TOKEN         (الزامی)  - توکن ربات از BotFather
  CHANNEL_USERNAME  (اختیاری) - مثلاً Arzyabi_eam  یا  @Arzyabi_eam
  DATA_DIR          (اختیاری) - مسیر پوشه‌ی داده
"""

import json
import os
import re
import tempfile
import time
from datetime import datetime

import requests

# ------------------------------------------------------------------ پیکربندی
TOKEN = os.environ.get("BOT_TOKEN", "").strip()
if not TOKEN:
    raise SystemExit("❌ متغیر BOT_TOKEN تعریف نشده است (فایل /etc/arzyabi-bot/bot.env)")

CHANNEL_USERNAME = os.environ.get("CHANNEL_USERNAME", "").strip().lstrip("@")
OWNER_ID_ENV = os.environ.get("OWNER_ID", "").strip()
try:
    EXIT_AFTER_MINUTES = float(os.environ.get("EXIT_AFTER_MINUTES", "0") or 0)
except ValueError:
    EXIT_AFTER_MINUTES = 0.0

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("DATA_DIR", os.path.join(BASE_DIR, "data"))
os.makedirs(DATA_DIR, exist_ok=True)
CONFIG_FILE = os.path.join(DATA_DIR, "config.json")
LOG_FILE = os.path.join(DATA_DIR, "log.json")
SCHED_FILE = os.path.join(DATA_DIR, "scheduled.json")

API = "https://api.telegram.org/bot" + TOKEN
FILE_API = "https://api.telegram.org/file/bot" + TOKEN
UA = "Mozilla/5.0 (arzyabi-admin-bot)"

# ------------------------------------------------------------------ ابزارها


def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


config = load_json(CONFIG_FILE, {})
log = load_json(LOG_FILE, {"actions": []})
scheduled = load_json(SCHED_FILE, {"items": []})
BOT_ID = None


class BotError(Exception):
    pass


def tg(method, params=None, files=None):
    """صدور یک درخواست به API تلگرام."""
    params = dict(params or {})
    r = requests.post(API + "/" + method, data=params, files=files, timeout=90)
    data = r.json()
    if not data.get("ok"):
        raise BotError(data.get("description") or "خطای نامشخص")
    return data["result"]


def add_log(action, detail=""):
    log["actions"].append(
        {"t": datetime.now().strftime("%Y/%m/%d %H:%M"), "action": action, "detail": detail}
    )
    log["actions"] = log["actions"][-200:]
    save_json(LOG_FILE, log)


def fa_digits(s):
    """تبدیل اعداد فارسی/عربی به انگلیسی (طول متن حفظ می‌شود)."""
    if not s:
        return s
    table = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "0123456789" * 2)
    return s.translate(table)


def reply(chat_id, text):
    try:
        tg("sendMessage", {"chat_id": chat_id, "text": text})
    except Exception as e:
        print("خطا در ارسال پاسخ:", e)


def extract_message_id(text):
    """درآوردن شماره‌ی پیام از متن/لینک: حذف 123 یا حذف https://t.me/channel/123"""
    t = fa_digits(text).strip()
    m = re.search(r"(?:t\.me/c/[^/\s]+/|t\.me/[A-Za-z_][\w]*/)(\d+)", t)
    if m:
        return int(m.group(1))
    if re.fullmatch(r"-?\d+", t):
        return int(t)
    return None


def resolve_user_id(text):
    """تبدیل @username یا شماره به user id."""
    t = fa_digits(text).strip().lstrip("@")
    if re.fullmatch(r"-?\d+", t):
        return int(t)
    if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{3,31}", t):
        try:
            html = requests.get("https://t.me/" + t, headers={"User-Agent": UA}, timeout=15).text
            m = re.search(r"ID:\s*(\d+)", html)
            if m:
                return int(m.group(1))
        except Exception:
            pass
    return None


# ------------------------------------------------------------------ کانال


def get_channel_id():
    return config.get("channel_id")


def set_channel(username):
    global config
    username = fa_digits(username).strip().lstrip("@")
    chat = tg("getChat", {"chat_id": "@" + username})
    if chat.get("type") != "channel":
        raise BotError("آیدی داده‌شده یک کانال تلگرامی نیست")
    config["
