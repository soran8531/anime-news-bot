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

translator = GoogleTranslator(source="en", target="fa")


# ---------- توابع کمکی ----------

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


def log_to_history(title_en: str, summary_en: str, title_fa: str, summary_fa: str,
                    link: str, source: str, category: str):
    """این خبر رو به ربات تعاملی (PythonAnywhere) هم گزارش می‌ده تا توی
    دکمه‌ها و مینی‌اپ قابل مشاهده باشه. اگه تنظیم نشده باشه، بی‌صدا رد می‌شه."""
    if not WEBHOOK_LOG_URL or not LOG_SECRET:
        return
    try:
        resp = requests.post(
            WEBHOOK_LOG_URL,
            json={
                "secret": LOG_SECRET,
                "items": [
                    {
                        "title_en": title_en,
                        "summary_en": summary_en,
                        "title_fa": title_fa,
                        "summary_fa": summary_fa,
                        "link": link,
                        "source": source,
                        "category": category,
                    }
                ],
            },
            timeout=10,
        )
        if not resp.ok:
            print(f"⚠️ گزارش به مینی‌اپ ناموفق بود: {resp.status_code} - {resp.text[:200]}")
    except Exception as e:
        print(f"⚠️ نشد به ربات تعاملی گزارش بدم: {e}")


def detect_category(title: str, summary: str) -> str:
    """از روی کلمات کلیدی توی متن انگلیسی تشخیص می‌ده خبر مربوط به انیمه، مانگا یا مانهواست."""
    text = f"{title} {summary}".lower()
    if "manhwa" in text:
        return "manhwa"
    if "manga" in text or "manhua" in text or "light novel" in text:
        return "manga"
    return "anime"


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
            category = detect_category(title_en, summary_en)
            category_emoji = {"anime": "🎬", "manga": "📖", "manhwa": "🇰🇷"}[category]
            category_label = {"anime": "انیمه", "manga": "مانگا", "manhwa": "مانهوا"}[category]

            title_fa = translate_safe(title_en)
            summary_fa = translate_safe(summary_en)

            message = (
                f"{category_emoji} <b>{title_fa}</b>\n\n"
                f"{summary_fa}\n\n"
                f"🏷️ دسته: {category_label}\n"
                f"📰 منبع: {source_name}\n"
                f"🔗 {link}"
            )

            if send_telegram_message(message):
                new_sent_ids.add(entry_id)
                total_sent += 1
                print(f"✅ ارسال شد: {title_en[:60]}")
                log_to_history(title_en, summary_en, title_fa, summary_fa, link, source_name, category)
                time.sleep(1.5)  # برای رعایت محدودیت نرخ تلگرام و گوگل ترنسلیت

    save_sent_ids(new_sent_ids)
    print(f"\nتمام شد. تعداد خبرهای ارسال‌شده در این اجرا: {total_sent}")


if __name__ == "__main__":
    main()
