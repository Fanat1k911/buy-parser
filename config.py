import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

WB_DEST_ID = os.getenv("WB_DEST_ID", "-1216601")
AVITO_REGION_SLUG = os.getenv("AVITO_REGION_SLUG", "sankt-peterburg")
AVITO_TITLE_ONLY = os.getenv("AVITO_TITLE_ONLY", "true").lower() == "true"

HEADLESS = os.getenv("HEADLESS", "true").lower() == "true"

DEFAULT_SCAN_INTERVAL_MINUTES = int(os.getenv("SCAN_INTERVAL_MINUTES", "5"))
WORKER_TICK_MINUTES = int(os.getenv("WORKER_TICK_MINUTES", "1"))

# Пробовать вычислить прямую ссылку на картинку товара WB через перебор
# CDN-корзин (basket). Надёжно, но добавляет задержку на каждый товар WB.
FETCH_WB_IMAGES = os.getenv("FETCH_WB_IMAGES", "false").lower() == "true"
