"""
ربات اخبار انیمه
هر بار اجرا می‌شه: فیدهای خبری انیمه رو می‌خونه، خبرهای جدید (که قبلاً فرستاده نشدن) رو
به فارسی ترجمه می‌کنه و توی تلگرام می‌فرسته.
"""

import json
import os
import time
from pathlib import Path

import feedparser
import requests
from deep_translator import GoogleTranslator

# ---------- تنظیمات ----------

# فیدهای خبری (می‌تونی اضافه/کم کنی)
FEEDS = {
    "Anime News Network": "https://www.animenewsnetwork.com/all/rss.xml",
    "Anime Corner": "https://animecorner.me/feed/",
    "Crunchyroll News": "https://www.crunchyroll.com/newsrss",
}

STATE_FILE = Path(__file__).parent / "sent_ids.json"
MAX_ITEMS_PER_FEED = 8  # حداکثر تعداد خبر از هر منبع در هر اجرا (برای جلوگیری از اسپم)

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# آدرس ربات تعاملی (PythonAnywhere) برای ثبت تاریخچه‌ی خبرها.
# اگه خالی بگذاری، این قابلیت غیرفعال می‌شه و فقط ارسال به تلگرام انجام می‌شه.
WEBHOOK_LOG_URL = os.environ.get("WEBHOOK_LOG_URL", "")  # مثلاً https://sisisi.pythonanywhere.com/log_news
LOG_SECRET = os.environ.get("LOG_SECRET", "")
print(f"DEBUG: WEBHOOK_LOG_URL={WEBHOOK_LOG_URL!r}, LOG_SECRET={'set' if LOG_SECRET else 'EMPTY'}")

translator = GoogleTranslator(source="en", target="fa")

# برچسب و ایموجی هر دسته
CATEGORY_META = {
    "anime": {"emoji": "🎬", "label": "انیمه"},
    "manga": {"emoji": "📖", "label": "مانگا"},
}


# ---------- توابع کمکی ----------

def detect_category(text: str) -> str:
    """
    تشخیص دسته‌ی خبر از روی متنش (عنوان + خلاصه).
    اگه کلمه‌ی 'manga' توش باشه -> مانگا
    وگرنه -> انیمه
    """
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
    # فقط ۵۰۰ مورد آخر رو نگه می‌داریم که فایل بی‌نهایت بزرگ نشه
    trimmed = list(ids)[-500:]
    STATE_FILE.write_text(json.dumps(trimmed, ensure_ascii=False), encoding="utf-8")


def translate_safe(text: str) -> str:
    """ترجمه با مدیریت خطا (اگه ترجمه شکست بخوره، متن اصلی برگردونده می‌شه)."""
    if not text:
        return ""
    try:
        # گوگل ترنسلیت محدودیت طول داره، برای احتیاط کوتاه می‌کنیم
        return translator.translate(text[:1500])
    except Exception as e:
        print(f"⚠️ خطا در ترجمه: {e}")
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
        print(f"⚠️ خطا در ارسال به تلگرام: {resp.status_code} - {resp.text}")
    return resp.ok


def log_to_history(title: str, summary: str, link: str, source: str, category: str):
    """این خبر رو به ربات تعاملی (PythonAnywhere) هم گزارش می‌ده تا توی
    دکمه‌های «اخبار انیمه/مانگا» قابل مشاهده باشه. اگه تنظیم نشده باشه، بی‌صدا رد می‌شه."""
    if not WEBHOOK_LOG_URL or not LOG_SECRET:
        return
    try:
        resp = requests.post(
            WEBHOOK_LOG_URL,
            json={
                "secret": LOG_SECRET,
                "items": [
                    {
                        "title": title,
                        "summary": summary,
                        "link": link,
                        "source": source,
                        "category": category,
                        "sent_at": time.time(),
                    }
                ],
            },
            timeout=10,
        )
        print(f"DEBUG log_to_history response: {resp.status_code} - {resp.text[:200]}")
    except Exception as e:
        print(f"⚠️ نشد به ربات تعاملی گزارش بدم: {e}")


def clean_html(raw: str) -> str:
    """حذف تگ‌های ساده HTML که بعضی فیدها توی خلاصه‌شون دارن."""
    import re
    text = re.sub("<[^<]+?>", "", raw or "")
    return text.strip()


# ---------- منطق اصلی ----------

def main():
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        raise SystemExit(
            "❌ متغیرهای محیطی TELEGRAM_BOT_TOKEN و TELEGRAM_CHAT_ID تنظیم نشدن."
        )

    sent_ids = load_sent_ids()
    new_sent_ids = set(sent_ids)
    total_sent = 0

    for source_name, feed_url in FEEDS.items():
        print(f"در حال بررسی منبع: {source_name}")
        try:
            feed = feedparser.parse(feed_url)
        except Exception as e:
            print(f"⚠️ نشد فید {source_name} خونده بشه: {e}")
            continue

        entries = feed.entries[:MAX_ITEMS_PER_FEED]

        # از قدیمی‌ترین به جدیدترین بفرست تا ترتیب توی تلگرام درست باشه
        for entry in reversed(entries):
            entry_id = entry.get("id") or entry.get("link")
            if not entry_id or entry_id in sent_ids:
                continue

            title_en = entry.get("title", "").strip()
            summary_en = clean_html(entry.get("summary", ""))
            link = entry.get("link", "")

            category = detect_category(f"{title_en} {summary_en}")
            meta = CATEGORY_META[category]

            title_fa = translate_safe(title_en)
            summary_fa = translate_safe(summary_en)

            message = (
                f"{meta['emoji']} <b>{title_fa}</b>\n\n"
                f"{summary_fa}\n\n"
                f"🏷 دسته: {meta['label']}\n"
                f"📰 منبع: {source_name}\n"
                f"🔗 {link}"
            )

            if send_telegram_message(message):
                new_sent_ids.add(entry_id)
                total_sent += 1
                print(f"✅ ارسال شد [{meta['label']}]: {title_en[:60]}")
                log_to_history(title_fa, summary_fa, link, source_name, category)
                time.sleep(1.5)  # برای رعایت محدودیت نرخ تلگرام و گوگل ترنسلیت

    save_sent_ids(new_sent_ids)
    print(f"\nتمام شد. تعداد خبرهای ارسال‌شده در این اجرا: {total_sent}")


if __name__ == "__main__":
    main()
