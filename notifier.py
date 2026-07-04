import requests

import config


def send_telegram_message(text: str) -> bool:
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        print("[NOTIFIER] Telegram не настроен (нет TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID в .env) — пропуск.")
        return False

    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": config.TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }
    try:
        resp = requests.post(url, json=payload, timeout=10)
        resp.raise_for_status()
        return True
    except Exception as e:
        print(f"[NOTIFIER] Не удалось отправить сообщение в Telegram: {e}")
        return False


def format_deal_message(product_name: str, offer: dict, target_price: float) -> str:
    return (
        "🔥 <b>Найдена выгодная цена!</b>\n\n"
        f"Запрос: <b>{product_name}</b>\n"
        f"Площадка: {offer['platform']}\n"
        f"Товар: {offer['title']}\n"
        f"Цена: <b>{offer['price']:,.0f} ₽</b> (цель: {target_price:,.0f} ₽)\n"
        f"Ссылка: {offer['url']}"
    )
