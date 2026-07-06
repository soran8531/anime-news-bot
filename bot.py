# bot.py
"""
ربات اخبار انیمه (نسخه Mini App Ready)
- خبر می‌خونه، ترجمه می‌کنه، به تلگرام می‌فرسته
- هم متن انگلیسی، هم فارسی رو به Backend می‌فرسته برای Mini App
"""

import json
import os
import time
from pathlib import Path

import feedparser
import requests
from deep_translator import GoogleTranslator

# ---------- تنظیمات ----------
FEEDS = {
    "Anime News Network": "https://www.animenewsnetwork.com/all/rss.xml",
    "Anime Corner": "https://animecorner.me/feed/",
    "Crunchyroll News": "https://www.crunchyroll.com/newsrss",
}

STATE_FILE = Path(__file__).parent / "sent_ids.json"
MAX_ITEMS_PER_FEED = 8

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# آدرس وب‌هوک بک‌اند (PythonAnywhere) - باید دقیقاً همون /log_news باشه
WEBHOOK_LOG_URL = os.environ.get("WEBHOOK_LOG_URL", "")
LOG_SECRET = os.environ.get("LOG_SECRET", "")

translator = GoogleTranslator(source="en", target="fa")

CATEGORY_META = {
    "anime": {"emoji": "🎬", "label": "Anime", "label_fa": "انیمه"},
    "manga": {"emoji": "📖", "label": "Manga", "label_fa": "مانگا"},
}

# ---------- توابع کمکی ----------
def detect_category(text: str) -> str:
    t = (text or "").lower()
    if "manga" in t:
        return "manga"
    return "anime"

def load_sent_ids() -> set:
    if STATE_FILE.exists():
        try:
            return set(json.loads(STATE_FILE.read_text(encoding="utf-8")))
        except Exception:
            return set()
    return set()

def save_sent_ids(ids: set):
    trimmed = list(ids)[-500:]
    STATE_FILE.write_text(json.dumps(trimmed, ensure_ascii=False), encoding="utf-8")

def translate_safe(text: str) -> str:
    if not text: return ""
    try:
        return translator.translate(text[:1500])
    except Exception as e:
        print(f"⚠️ Translation error: {e}")
        return text

def send_telegram_message(text: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }
    resp = requests.post(url, data=payload, timeout=20)
    if not resp.ok:
        print(f"⚠️ Telegram send error: {resp.status_code} - {resp.text}")
    return resp.ok

def clean_html(raw: str) -> str:
    import re
    text = re.sub("<[^<]+?>", "", raw or "")
    return text.strip()

# ---------- ارسال به بک‌اند (Mini App Backend) ----------
def log_to_backend(item_data: dict):
    """
    خبر رو به بک‌اند مینی‌اپ می‌فرسته.
    item_data شامل: title_en, summary_en, title_fa, summary_fa, link, source, category, sent_at
    """
    if not WEBHOOK_LOG_URL or not LOG_SECRET:
        return
    try:
        resp = requests.post(
            WEBHOOK_LOG_URL,
            json={"secret": LOG_SECRET, "items": [item_data]},
            timeout=10,
        )
        if not resp.ok:
            print(f"⚠️ Backend log failed: {resp.status_code} - {resp.text[:200]}")
    except Exception as e:
        print(f"⚠️ Backend log exception: {e}")

# ---------- منطق اصلی ----------
def main():
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        raise SystemExit("❌ ENV vars missing: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID")

    sent_ids = load_sent_ids()
    new_sent_ids = set(sent_ids)
    total_sent = 0

    for source_name, feed_url in FEEDS.items():
        print(f"Checking source: {source_name}")
        try:
            feed = feedparser.parse(feed_url)
        except Exception as e:
            print(f"⚠️ Feed parse error {source_name}: {e}")
            continue

        entries = feed.entries[:MAX_ITEMS_PER_FEED]

        for entry in reversed(entries):
            entry_id = entry.get("id") or entry.get("link")
            if not entry_id or entry_id in sent_ids:
                continue

            title_en = entry.get("title", "").strip()
            summary_en = clean_html(entry.get("summary", ""))
            link = entry.get("link", "")

            category = detect_category(f"{title_en} {summary_en}")
            meta = CATEGORY_META[category]

            # ترجمه به فارسی
            title_fa = translate_safe(title_en)
            summary_fa = translate_safe(summary_en)

            # ۱. ارسال به تلگرام (فقط فارسی، همانطور که قبلاً بود)
            message = (
                f"{meta['emoji']} <b>{title_fa}</b>\n\n"
                f"{summary_fa}\n\n"
                f"🏷 {meta['label_fa']}\n"
                f"📰 {source_name}\n"
                f"🔗 {link}"
            )

            if send_telegram_message(message):
                new_sent_ids.add(entry_id)
                total_sent += 1
                print(f"✅ Sent [{meta['label_fa']}]: {title_en[:60]}")

                # ۲. لاگ کردن در بک‌اند مینی‌اپ (هر دو زبان)
                log_to_backend({
                    "title_en": title_en,
                    "summary_en": summary_en,
                    "title_fa": title_fa,
                    "summary_fa": summary_fa,
                    "link": link,
                    "source": source_name,
                    "category": category, # 'anime' or 'manga'
                    "sent_at": time.time(),
                })
                time.sleep(1.5)

    save_sent_ids(new_sent_ids)
    print(f"\nDone. Total sent: {total_sent}")

if __name__ == "__main__":
    main()
