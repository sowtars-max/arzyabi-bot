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
    config["channel_id"] = chat["id"]
    config["channel_title"] = chat.get("title", username)
    config["channel_username"] = username
    save_json(CONFIG_FILE, config)
    return chat


def ensure_channel_ready(chat_id):
    """بازگرداندن (True, '') در صورت آمادگی کامل کانال."""
    global BOT_ID
    if not get_channel_id():
        reply(chat_id, "ابتدا نام کانال را برایم بفرستید:\nکانال: @نام_کانال")
        return False, "no channel"
    if BOT_ID is None:
        BOT_ID = tg("getMe")["id"]
    try:
        member = tg("getChatMember", {"chat_id": get_channel_id(), "user_id": BOT_ID})
    except BotError as e:
        reply(chat_id, f"❌ خطا در ارتباط با کانال: {e}")
        return False, str(e)
    if member.get("status") != "administrator":
        reply(
            chat_id,
            "⚠️ ربات هنوز ادمین کانال نیست (یا مجوزهاش را از دست داده).\n"
            "لطفاً از تنظیمات کانال، ربات را به عنوان ادمین با مجوزهای "
            "Post / Delete / Pin / Ban / Edit اضافه کنید.",
        )
        return False, "not admin"
    return True, ""


def channel_link(message_id):
    un = config.get("channel_username")
    if un:
        return f"https://t.me/{un}/{message_id}"
    cid = get_channel_id()
    if cid and str(cid).startswith("-100"):
        return f"https://t.me/c/{str(cid)[4:]}/{message_id}"
    return "n/a"


# ------------------------------------------------------------------ انتشار


def publish_text(body, chat_id, source="دستی"):
    ok, _ = ensure_channel_ready(chat_id)
    if not ok:
        return
    try:
        res = tg("sendMessage", {"chat_id": get_channel_id(), "text": body})
    except BotError as e:
        reply(chat_id, f"❌ خطا در انتشار: {e}")
        return
    mid = res["message_id"]
    add_log("publish", f"پست {mid} ({source})")
    reply(chat_id, f"✅ پست منتشر شد.\nشماره: {mid}\nلینک: {channel_link(mid)}")


MEDIA_METHOD = {
    "photo": ("sendPhoto", "photo"),
    "video": ("sendVideo", "video"),
    "animation": ("sendVideo", "video"),
    "document": ("sendDocument", "document"),
    "audio": ("sendAudio", "audio"),
    "video_note": ("sendVideoNote", "video_note"),
}


def send_media_to_channel(msg, caption):
    """دانلود فایل از تلگرام و ارسال مجدد به کانال (بدون برچسب «Forwarded»)."""
    msg = dict(msg)
    media_key = next((k for k in MEDIA_METHOD if k in msg), None)
    if not media_key:
        raise BotError("فایلی برای ارسال پیدا نشد")
    item = msg[media_key]
    if media_key == "photo":
        item = item[-1]
    finfo = tg("getFile", {"file_id": item["file_id"]})
    r = requests.get(FILE_API + "/" + finfo["file_path"], timeout=120)
    r.raise_for_status()
    method, field = MEDIA_METHOD[media_key]
    suffix = os.path.splitext(finfo["file_path"])[1] or ".bin"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(r.content)
        tmp_path = tmp.name
    try:
        with open(tmp_path, "rb") as f:
            params = {"chat_id": get_channel_id()}
            if caption:
                params["caption"] = caption[:1024]
            res = tg(method, params, files={field: f})
        return res["message_id"]
    finally:
        os.unlink(tmp_path)


def handle_media(msg):
    """فایل‌هایی که با عنوان «انتشار» فرستاده می‌شوند."""
    chat_id = msg["chat_id"]
    caption = fa_digits((msg.get("caption") or "")).strip()
    if not caption.startswith("انتشار"):
        reply(
            chat_id,
            "📎 فایل شما را دیدم ولی عنوانش «انتشار» نبود.\n"
            "برای انتشار، فایل را با عنوان: انتشار  (یا: انتشار: متنِ پست) بفرستید.",
        )
        return
    body = caption[len("انتشار"):].strip(" \t:-–—")
    if not any(k in msg for k in MEDIA_METHOD):
        reply(chat_id, "❌ این پیام فاقد فایل تصویری/ویدئو/سند است.")
        return
    ok, _ = ensure_channel_ready(chat_id)
    if not ok:
        return
    try:
        mid = send_media_to_channel(msg, body)
    except Exception as e:
        reply(chat_id, f"❌ خطا در انتشار فایل: {e}")
        return
    add_log("publish", f"پست {mid} (فایل)")
    reply(chat_id, f"✅ پست منتشر شد.\nشماره: {mid}\nلینک: {channel_link(mid)}")


# ------------------------------------------------------------------ دستورات


HELP = """🛠️ ربات مدیریت کانال Arzyabi

📢 انتشار:
• انتشار: متن پست
• فایل (عکس/ویدئو/سند) را با عنوان «انتشار» بفرستید
• زمان‌بندی: 2026/09/30 14:00 متن پست
• لیست زمان‌بندی‌ها
• لغو زمان‌بندی 1

🗑️ مدیریت:
• حذف 123   (یا لینک کامل پست)
• ویرایش 123 متن جدید
• پین 123
• بردار پین 123
• بن @یوزرنیم   یا   بن 123456789
• رفع بن @یوزرنیم

📊 اطلاعات:
• آمار
• گزارش   (آخرین کارهای ربات)
• کانال: @نام_کانال

💡 شماره‌ی هر پست را از لینکش می‌گیرید (t.me/کانال/شماره) یا از گزارش انتشار."""


def cmd_channel(chat_id, t, orig):
    m = re.search(r"(@?[\w]{3,32})", t)
    if not m:
        reply(chat_id, "فرمت صحیح: کانال: @نام_کانال")
        return
    try:
        chat = set_channel(m.group(1))
        add_log("channel", chat.get("title", m.group(1)))
        reply(chat_id, f"✅ کانال «{chat.get('title')}» تنظیم شد.\nدستور «آمار» را بفرستید تا بررسی شود.")
    except BotError as e:
        reply(chat_id, f"❌ کانال پیدا نشد یا اشتباه است: {e}")


def cmd_ban(chat_id, t, unban=False):
    key = "رفع بن" if unban else "بن"
    arg = t[len(key):].strip()
    verb = "رفع بن" if unban else "بن"
    if not arg:
        reply(chat_id, f"فرمت: {verb} @یوزرنیم   یا   {verb} 123456789")
        return
    uid = resolve_user_id(arg)
    if not uid:
        reply(
            chat_id,
            f"❌ کاربر «{arg}» پیدا نشد.\n"
            "💡 اگر یوزرنیم عمومی ندارد، آیدی عددی‌اش را از صفحه‌ی t.me/یوزرنیم "
            "(بخش ID) بردارید و با همان عدد فرستاد.",
        )
        return
    ok, _ = ensure_channel_ready(chat_id)
    if not ok:
        return
    try:
        if unban:
            tg("unbanChatMember", {"chat_id": get_channel_id(), "user_id": uid})
        else:
            tg("banChatMember", {"chat_id": get_channel_id(), "user_id": uid})
        add_log("unban" if unban else "ban", arg)
        reply(chat_id, f"{'✅ بن برداشته شد: ' if unban else '🔒 بن شد: '}{arg}")
    except BotError as e:
        reply(
            chat_id,
            f"❌ خطا در {verb}: {e}\n"
            "💡 اگر کاربر تا حالا در کانال/کامنت‌ها حضور نداشته، می‌توانید از "
            "پنل ادمین کانال هم اقدام کنید.",
        )


def cmd_delete(chat_id, t):
    arg = re.sub(r"^(حذف کردن|حذف|پاک کردن|پاک)", "", t).strip()
    mid = extract_message_id(arg)
    if not mid:
        reply(chat_id, "فرمت: حذف 123   یا   حذف https://t.me/کانال/123")
        return
    ok, _ = ensure_channel_ready(chat_id)
    if not ok:
        return
    try:
        tg("deleteMessage", {"chat_id": get_channel_id(), "message_id": mid})
        add_log("delete", str(mid))
        reply(chat_id, f"🗑️ پست {mid} حذف شد.")
    except BotError as e:
        reply(chat_id, f"❌ خطا در حذف: {e}")


def cmd_edit(chat_id, t, orig):
    m = re.match(r"^ویرایش\s+(\d+)\s+(.+)$", t, re.S)
    if not m:
        reply(chat_id, "فرمت: ویرایش 123 متنِ جدید")
        return
    mid = int(m.group(1))
    new_text = orig[m.start(2):].strip()
    if len(new_text) > 4096:
        reply(chat_id, "❌ متن جدید خیلی طولانی است (حداکثر ۴۰۹۶ کاراکتر).")
        return
    ok, _ = ensure_channel_ready(chat_id)
    if not ok:
        return
    try:
        tg("editMessageText", {"chat_id": get_channel_id(), "message_id": mid, "text": new_text})
        add_log("edit", str(mid))
        reply(chat_id, f"✏️ پست {mid} ویرایش شد.")
    except BotError as e:
        reply(chat_id, f"❌ خطا در ویرایش: {e}")


def cmd_pin(chat_id, t, unpin=False):
    arg = re.sub(r"^(بردار )?پین", "", t).strip()
    mid = extract_message_id(arg)
    if not mid:
        reply(chat_id, "فرمت: پین 123   یا   بردار پین 123")
        return
    ok, _ = ensure_channel_ready(chat_id)
    if not ok:
        return
    try:
        if unpin:
            tg("unpinChatMessage", {"chat_id": get_channel_id(), "message_id": mid})
            add_log("unpin", str(mid))
            reply(chat_id, f"📌 پین پست {mid} برداشته شد.")
        else:
            tg("pinChatMessage", {"chat_id": get_channel_id(), "message_id": mid, "disable_notification": True})
            add_log("pin", str(mid))
            reply(chat_id, f"📌 پست {mid} پین شد.")
    except BotError as e:
        reply(chat_id, f"❌ خطا: {e}")


def cmd_stats(chat_id):
    if not get_channel_id():
        reply(chat_id, "ابتدا «کانال: @نام_کانال» را بفرستید.")
        return
    try:
        chat = tg("getChat", {"chat_id": get_channel_id()})
    except BotError as e:
        reply(chat_id, f"❌ {e}")
        return
    from collections import Counter

    c = Counter(a["action"] for a in log["actions"])
    lines = [f"📊 {chat.get('title', 'کانال')}"]
    if "member_count" in chat:
        lines.append(f"👥 اعضا: {chat['member_count']}")
    lines += [
        f"📢 انتشار: {c.get('publish', 0)}",
        f"🗑️ حذف: {c.get('delete', 0)}",
        f"✏️ ویرایش: {c.get('edit', 0)}",
        f"🔒 بن: {c.get('ban', 0)} | 🟢 رفع بن: {c.get('unban', 0)}",
        f"⏰ زمان‌بندی‌های آینده: {len(scheduled['items'])}",
        f"🕐 وقت (تهران): {datetime.now():%Y/%m/%d %H:%M}",
        "— (اعداد بر اساس ۲۰۰ کار آخر ربات)",
    ]
    reply(chat_id, "\n".join(lines))


def cmd_report(chat_id):
    actions = log["actions"][-15:][::-1]
    if not actions:
        reply(chat_id, "هنوز کاری ثبت نشده است.")
        return
    lines = ["🧾 ۱۵ کار آخر ربات:"]
    for a in actions:
        lines.append(f"• {a['t']} — {a['action']}" + (f" ({a['detail']})" if a.get("detail") else ""))
    reply(chat_id, "\n".join(lines))


# ------------------------------------------------------------------ زمان‌بندی


SCHED_RE = re.compile(
    r"^زمان‌بندی\s*[:：]?\s*(\d{4})[/-](\d{1,2})[/-](\d{1,2})\s+(\d{1,2}):(\d{2})\s+(.+)$", re.S
)


def cmd_schedule(chat_id, t, orig):
    m = SCHED_RE.match(t)
    if not m:
        reply(chat_id, "فرمت: زمان‌بندی: 2026/09/30 14:00 متن پست")
        return
    y, mo, d, h, mi = (int(m.group(i)) for i in range(1, 6))
    body = orig[m.start(6):].strip()
    try:
        dt = datetime(y, mo, d, h, mi)
    except ValueError:
        reply(chat_id, "❌ تاریخ/ساعت واردشده معتبر نیست (فرمت: سال/ماه/روز ساعت:دقیقه).")
        return
    if dt <= datetime.now():
        reply(chat_id, "❌ زمان باید در آینده باشد (وقت به وقت تهران).")
        return
    item = {"id": scheduled.get("next_id", 1), "dt": dt.strftime("%Y-%m-%d %H:%M"), "text": body}
    scheduled["items"].append(item)
    scheduled["next_id"] = scheduled.get("next_id", 1) + 1
    save_json(SCHED_FILE, scheduled)
    add_log("schedule", dt.strftime("%Y/%m/%d %H:%M"))
    reply(chat_id, f"⏰ پست برای {dt:%Y/%m/%d %H:%M} (وقت تهران) ثبت شد.\nشماره‌ی این زمان‌بندی: {item['id']}")


def cmd_list_schedule(chat_id):
    items = scheduled["items"]
    if not items:
        reply(chat_id, "زمان‌بندی فعالی وجود ندارد.")
        return
    lines = ["⏰ زمان‌بندی‌های آینده:"]
    for it in items:
        lines.append(f"{it['id']}. {it['dt']} — {it['text'][:40]}{'…' if len(it['text']) > 40 else ''}")
    reply(chat_id, "\n".join(lines))


def cmd_cancel_schedule(chat_id, t):
    m = re.search(r"(\d+)", t)
    if not m:
        reply(chat_id, "فرمت: لغو زمان‌بندی 1")
        return
    nid = int(m.group(1))
    before = len(scheduled["items"])
    scheduled["items"] = [i for i in scheduled["items"] if i["id"] != nid]
    if len(scheduled["items"]) == before:
        reply(chat_id, f"❌ زمان‌بندی با شماره‌ی {nid} پیدا نشد.")
        return
    save_json(SCHED_FILE, scheduled)
    add_log("unschedule", str(nid))
    reply(chat_id, f"✅ زمان‌بندی {nid} لغو شد.")


def check_scheduled():
    now = datetime.now()
    if not scheduled["items"]:
        return
    keep, due = [], []
    for it in scheduled["items"]:
        if datetime.strptime(it["dt"], "%Y-%m-%d %H:%M") <= now:
            due.append(it)
        else:
            keep.append(it)
    if not due:
        return
    scheduled["items"] = keep
    save_json(SCHED_FILE, scheduled)
    owner = config.get("owner_id")
    for it in due:
        try:
            publish_text(it["text"], owner, source="زمان‌بندی")
        except Exception as e:
            add_log("schedule-error", str(e))


# ------------------------------------------------------------------ اصلی


def process_command(msg):
    chat_id = msg["chat_id"]
    orig = (msg.get("text") or "").strip()
    t = fa_digits(orig)

    if not t:
        handle_media(msg)
        return

    if t.startswith("لیست زمان‌بندی"):
        cmd_list_schedule(chat_id)
    elif t.startswith("لغو زمان‌بندی"):
        cmd_cancel_schedule(chat_id, t)
    elif t.startswith("زمان‌بندی"):
        cmd_schedule(chat_id, t, orig)
    elif t.startswith("رفع بن"):
        cmd_ban(chat_id, t, unban=True)
    elif t.startswith("بن") or t.startswith("بک"):
        cmd_ban(chat_id, t, unban=False)
    elif t.startswith("بردار پین") or (t.startswith("پین") and "بردار" in t):
        cmd_pin(chat_id, t, unpin=True)
    elif t.startswith("پین"):
        cmd_pin(chat_id, t, unpin=False)
    elif t.startswith(("حذف", "پاک")):
        cmd_delete(chat_id, t)
    elif t.startswith("ویرایش"):
        cmd_edit(chat_id, t, orig)
    elif t.startswith("انتشار"):
        body = orig[len("انتشار"):].strip(" \t:-–—")
        if not body:
            reply(chat_id, "متن پست را بعد از «انتشار: » بنویسید.\nمثال: انتشار: امروز سالگرد راه‌اندازی کانال است 🎉")
        else:
            publish_text(body, chat_id)
    elif t.startswith("آمار"):
        cmd_stats(chat_id)
    elif t.startswith("گزارش"):
        cmd_report(chat_id)
    elif t.startswith("کانال"):
        cmd_channel(chat_id, t, orig)
    elif t in ("دستورات", "دستور", "help", "/help", "start", "/start", "menu", "/menu"):
        reply(chat_id, HELP)
    else:
        reply(chat_id, "🤔 متوجه نشدم. دستور «دستورات» را بفرستید تا لیست کارها را ببینید.")


def handle_message(msg):
    if msg.get("chat", {}).get("type") != "private":
        return
    uid = msg["from"]["id"]

    if OWNER_ID_ENV:
        if uid != int(OWNER_ID_ENV):
            reply(msg["chat_id"], "🚫 این ربات خصوصی است و فقط صاحب کانال می‌تواند از آن استفاده کند.")
            return
        process_command(msg)
        return

    if "owner_id" not in config:
        config["owner_id"] = uid
        config["owner_name"] = msg["from"].get("first_name", "")
        save_json(CONFIG_FILE, config)
        reply(
            msg["chat_id"],
            "✅ حساب شما به‌عنوان صاحب ربات ثبت شد.\n"
            "از این پس فقط شما می‌توانید با ربات کار کنید.\n"
            f"🔒 شماره‌ی شما: {uid}\n"
            "💡 اگر ربات روی GitHub اجرا می‌شود: برای قفل دائمی، همین عدد را به‌عنوان "
            "Secret به نام OWNER_ID در Settings → Secrets and variables → Actions ذخیره کنید.\n"
            "برای دیدن دستورات: دستور‌ها",
        )
        return

    if uid != config["owner_id"]:
        reply(msg["chat_id"], "🚫 این ربات خصوصی است و فقط صاحب کانال می‌تواند از آن استفاده کند.")
        return

    process_command(msg)


def main():
    global BOT_ID
    me = tg("getMe")
    BOT_ID = me["id"]
    print(f"🤖 ربات @{me.get('username')} (id: {me['id']}) راه‌اندازی شد.")
    if CHANNEL_USERNAME:
        try:
            chat = set_channel(CHANNEL_USERNAME)
            print(f"✅ کانال شناسایی شد: {chat.get('title')} (id: {chat['id']})")
        except Exception as e:
            print("⚠️ کانال به‌صورت خودکار شناسایی نشد:", e)
    if OWNER_ID_ENV:
        print(f"ℹ️ صاحب ربات با متغیر OWNER_ID ثابت شده است ({OWNER_ID_ENV}).")
    elif "owner_id" not in config:
        print("ℹ️ صاحب ربات هنوز ثبت نشده؛ اولین نفری که با ربات صحبت کند، صاحب آن می‌شود.")

    start_time = time.time()
    offset = None
    while True:
        try:
            params = {"timeout": 30, "allowed_updates": json.dumps(["message"])}
            if offset is not None:
                params["offset"] = offset
            for u in tg("getUpdates", params):
                offset = u["update_id"] + 1
                if "message" in u:
                    try:
                        handle_message(u["message"])
                    except Exception as e:
                        print("خطا در پردازش پیام:", e)
            check_scheduled()
        except BotError as e:
            print("خطای API:", e)
            time.sleep(5)
        except requests.RequestException as e:
            print("خطای شبکه:", e)
            time.sleep(10)
        except Exception as e:
            print("خطای غیرمنتظره:", e)
            time.sleep(5)
        if EXIT_AFTER_MINUTES and (time.time() - start_time) > EXIT_AFTER_MINUTES * 60:
            print("⏹ زمان اجرا تمام شد — برای تحویل به نمونه‌ی بعدی خارج می‌شوم.")
            break


if __name__ == "__main__":
    main()
