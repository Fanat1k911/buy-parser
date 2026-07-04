import argparse
import time
from datetime import datetime

import config
import database as db
from scraper import ScrapingEngine
from notifier import send_telegram_message, format_deal_message


def log(message):
    ts = datetime.now().strftime("%H:%M:%S")
    print("[" + ts + "] [WORKER] " + message)


def is_due(last_scanned_at, interval_minutes):
    if not last_scanned_at:
        return True
    last_dt = datetime.fromisoformat(last_scanned_at)
    elapsed_minutes = (datetime.now() - last_dt).total_seconds() / 60
    return elapsed_minutes >= interval_minutes


def scan_product(engine, prod_id, name, target_price):
    log("Сканирую: " + repr(name))
    offers = engine.scan_all(name)

    if not offers:
        log("Ничего не найдено для: " + repr(name))
        return

    db.update_offers(prod_id, offers)
    db.update_last_scanned(prod_id)

    for offer in offers:
        if offer["price"] <= target_price and not db.was_notified(offer["url"], offer["price"]):
            message = format_deal_message(name, offer, target_price)
            sent = send_telegram_message(message)
            if sent:
                db.mark_notified(offer["url"], offer["price"])
                log("Уведомление отправлено: " + offer["title"] + " — " + str(offer["price"]) + " руб.")


def tick():
    db.init_db()
    engine = ScrapingEngine()
    products = db.get_products()

    if not products:
        log("Нет товаров для отслеживания.")
        return

    due_count = 0
    for prod_id, name, target_price, last_scanned_at, interval_minutes in products:
        if is_due(last_scanned_at, interval_minutes):
            due_count += 1
            scan_product(engine, prod_id, name, target_price)

    if due_count == 0:
        log("Пока никому не пора сканироваться.")


def main():
    parser = argparse.ArgumentParser(description="Фоновый воркер мониторинга цен")
    parser.add_argument("--once", action="store_true",
                        help="Один проход по всем товарам, у кого подошёл интервал, и выход")
    args = parser.parse_args()

    if args.once:
        tick()
        return

    log("Запуск в режиме цикла. Проверка готовности товаров каждые " + str(config.WORKER_TICK_MINUTES) + " мин.")
    while True:
        tick()
        time.sleep(config.WORKER_TICK_MINUTES * 60)


if __name__ == "__main__":
    main()
