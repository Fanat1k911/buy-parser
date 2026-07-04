import re
import json
import time
import urllib.parse
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright

import config

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)

DEBUG_DIR = Path("debug_screenshots")
DEBUG_DIR.mkdir(exist_ok=True)


def log(tag, message):
    ts = datetime.now().strftime("%H:%M:%S")
    print("[" + ts + "] " + tag + " " + message)


def screenshot_name(prefix, query):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_query = query[:20].replace(" ", "_")
    filename = prefix + "_" + safe_query + "_" + ts + ".png"
    return str(DEBUG_DIR / filename)


def format_dt(iso_str):
    if not iso_str:
        return ""
    return iso_str[:16].replace("T", " ")


def extract_price_ru(text):
    matches = re.findall(r"(\d[\d\s\u00a0]{2,})\s*₽", text)
    if matches:
        digits = matches[0].replace(" ", "").replace("\u00a0", "")
        try:
            return float(digits)
        except ValueError:
            return 0.0
    return 0.0


def extract_title_generic(text):
    for line in text.split("\n"):
        line = line.strip()
        if line and "₽" not in line and not line.isdigit():
            return line
    return "Без названия"


def title_matches_query(title, query):
    title_lower = title.lower()
    words = [w for w in query.lower().split() if len(w) > 2]
    if not words:
        return True
    for w in words:
        if w not in title_lower:
            return False
    return True


def humanize_slug(slug):
    parts = slug.replace("-", " ").replace("_", " ").split()
    return " ".join(p.capitalize() for p in parts)


def scroll_to_load(page, steps=6, pause_ms=400):
    """Прокручивает страницу небольшими шагами, чтобы триггернуть
    lazy-load картинок у карточек, которые изначально вне экрана."""
    for _ in range(steps):
        page.mouse.wheel(0, 600)
        page.wait_for_timeout(pause_ms)


def extract_image_url(card_or_element):
    """Достаёт реальный URL картинки из <img>, даже если он лежит
    не в src (из-за lazy-load), а в data-src или srcset."""
    img_el = card_or_element.locator("img")
    if img_el.count() == 0:
        return None

    src = img_el.first.get_attribute("src")
    if src and not src.startswith("data:"):
        return src

    data_src = img_el.first.get_attribute("data-src")
    if data_src:
        return data_src

    srcset = img_el.first.get_attribute("srcset")
    if srcset:
        first_entry = srcset.split(",")[0].strip().split(" ")[0]
        if first_entry:
            return first_entry

    return None


def get_wb_image_url(nm_id):
    vol = nm_id // 100000
    part = nm_id // 1000

    for basket in range(30, 0, -1):
        basket_str = str(basket).zfill(2)
        candidate = (
                "https://basket-" + basket_str + ".wbbasket.ru/vol" + str(vol)
                + "/part" + str(part) + "/" + str(nm_id) + "/images/big/1.webp"
        )
        try:
            resp = requests.head(candidate, timeout=2)
            if resp.status_code == 200:
                return candidate
        except Exception:
            continue
    return None


class BaseScraper(ABC):
    @abstractmethod
    def search(self, query):
        pass


# ==========================================
# WILDBERRIES
# ==========================================
class WildberriesScraper(BaseScraper):
    # WB периодически меняет версию этого эндпоинта (была v9, стало v18+),
    # старые версии просто перестают работать и отдают ошибку в JSON.
    # Если поиск снова "сломается" - открой wildberries.ru, F12 -> Network ->
    # Fetch/XHR, вбей что-нибудь в поиск и посмотри актуальный URL запроса
    # к search.wb.ru (заодно сверь там же dest=... для своего региона) -
    # обнови версию и параметры тут.
    SEARCH_URL = "https://search.wb.ru/exactmatch/ru/common/v18/search"

    def search(self, query):
        results = []
        params = {
            "ab_testid": "false",
            "appType": 1,
            "curr": "rub",
            "dest": config.WB_DEST_ID,
            "inheritFilters": "false",
            "lang": "ru",
            "page": 1,
            "query": query,
            "resultset": "catalog",
            "sort": "popular",
            "spp": 30,
            "suppressSpellcheck": "false",
        }
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "*/*",
            "Referer": "https://www.wildberries.ru/",
        }

        log("[ENGINE WB]", "Запрос к API поиска: " + repr(query))

        backoff_seconds = 8
        attempt = 1
        max_attempts = 5
        while attempt <= max_attempts:
            try:
                resp = requests.get(self.SEARCH_URL, params=params, headers=headers, timeout=30)
                log("[ENGINE WB]", "Статус ответа: " + str(resp.status_code))

                if resp.status_code == 429:
                    log("[ENGINE WB]",
                        "Rate limit, жду " + str(backoff_seconds) + "с (попытка " + str(attempt) + "/" + str(
                            max_attempts) + ")")
                    time.sleep(backoff_seconds)
                    backoff_seconds = min(backoff_seconds * 2, 60)
                    attempt = attempt + 1
                    continue

                # ВАЖНО: раньше здесь сразу стоял raise_for_status() - при ошибке
                # мы теряли тело ответа, а именно в нём WB объясняет, что не так
                # (например: "поле resultset должно быть задано" - признак того,
                # что версия API в SEARCH_URL устарела).
                if resp.status_code != 200:
                    log("[ENGINE WB]", "Ошибка API (" + str(resp.status_code) + "): " + resp.text[:300])
                    break

                data = resp.json()

                # WB иногда возвращает 200, но с ошибкой прямо в теле - тоже логируем,
                # а не тихо считаем, что товаров просто нет.
                if isinstance(data, dict) and data.get("error"):
                    log("[ENGINE WB]", "API вернул ошибку в теле ответа: " + str(data.get("error")))
                    break

                # На разных версиях API товары лежат то в корне, то внутри "data" -
                # проверяем оба варианта, чтобы не сломаться при очередном обновлении версии.
                products = data.get("products") or data.get("data", {}).get("products", [])
                log("[ENGINE WB]", "Товаров в ответе: " + str(len(products)))

                if len(products) > 0:
                    first_product_json = json.dumps(products[0], ensure_ascii=False)
                    log("[ENGINE WB]", "Пример первого товара: " + first_product_json[:500])

                for p in products[:20]:
                    nm_id = p.get("id")
                    title = p.get("name", "Товар Wildberries")

                    price = 0.0
                    sale_price_u = p.get("salePriceU")
                    price_u = p.get("priceU")
                    sizes = p.get("sizes")

                    if sale_price_u:
                        price = sale_price_u / 100
                    elif price_u:
                        price = price_u / 100
                    elif sizes:
                        try:
                            price = sizes[0]["price"]["product"] / 100
                        except Exception:
                            price = 0.0

                    if nm_id and price > 0:
                        offer_url = "https://www.wildberries.ru/catalog/" + str(nm_id) + "/detail.aspx"

                        image_url = None
                        if config.FETCH_WB_IMAGES:
                            image_url = get_wb_image_url(nm_id)

                        results.append({
                            "platform": "Wildberries",
                            "title": title,
                            "price": price,
                            "url": offer_url,
                            "image_url": image_url,
                            "location": None,
                        })

                break

            except requests.exceptions.Timeout:
                log("[ENGINE WB]", "Таймаут, попытка " + str(attempt))
                time.sleep(backoff_seconds)
                backoff_seconds = min(backoff_seconds * 2, 60)
                attempt = attempt + 1
                continue
            except Exception as e:
                log("[ENGINE WB]", "Ошибка запроса к API: " + str(e))
                break

        if attempt > max_attempts:
            log("[ENGINE WB]",
                "Все попытки исчерпаны — похоже, лимит устойчивый, стоит подождать подольше перед следующим тестом.")

        log("[ENGINE WB]", "Найдено офферов: " + str(len(results)))
        return results


# ==========================================
# OZON
# ==========================================
class OzonScraper(BaseScraper):
    # Список признаков антибот-заглушки Ozon. Если в debug_screenshots увидишь
    # новую формулировку блокировки - просто добавь её сюда строкой.
    ANTIBOT_MARKERS = [
        "нет соединения", "ошибка", "антибот", "доступ ограничен",
        "подтвердите, что вы", "access denied", "captcha",
        "checking your browser", "just a moment",
    ]

    def search(self, query):
        results = []
        encoded_query = urllib.parse.quote(query)
        url = "https://www.ozon.ru/search/?text=" + encoded_query + "&from_global=true"
        log("[ENGINE OZON]", "Старт сканирования: " + url)

        browser = None
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=config.HEADLESS)
                try:
                    context = browser.new_context(
                        user_agent=USER_AGENT,
                        viewport={"width": 1440, "height": 900},
                        locale="ru-RU",
                    )
                    context.add_init_script(
                        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
                    )
                    page = context.new_page()

                    # networkidle почти никогда не наступает на Ozon - у них постоянно
                    # летит аналитика/трекинг в фоне, из-за этого раньше ловили таймаут
                    # ещё до того, как страница успевала отрисоваться.
                    page.goto(url, wait_until="domcontentloaded", timeout=45000)
                    page.wait_for_timeout(3000)
                    scroll_to_load(page)

                    page_title = page.title()
                    try:
                        page_text_lower = page.locator("body").inner_text(timeout=2000).lower()
                    except Exception:
                        page_text_lower = ""

                    log("[ENGINE OZON]", "Заголовок страницы: " + repr(page_title))
                    log("[ENGINE OZON]", "Итоговый URL: " + page.url)

                    title_lower = page_title.lower()
                    is_blocked = any(
                        marker in title_lower or marker in page_text_lower
                        for marker in self.ANTIBOT_MARKERS
                    )
                    if is_blocked:
                        log("[ENGINE OZON]", "Похоже на антибот-заглушку Ozon (детект автоматизации).")

                    # Даём карточкам шанс подгрузиться, но не падаем, если не дождались -
                    # попробуем собрать то, что уже успело отрисоваться в DOM.
                    try:
                        page.wait_for_selector('a[href*="/product/"]', timeout=10000)
                    except Exception:
                        pass

                    cards = page.locator('a[href*="/product/"]').all()[:20]
                    log("[ENGINE OZON]", "Найдено ссылок на товары: " + str(len(cards)))

                    # Сохраняем скриншот + HTML при любом провале (не только когда
                    # cards==0), чтобы можно было глазами посмотреть, что реально
                    # прислал Ozon, а не гадать по логам.
                    if len(cards) == 0 or is_blocked:
                        screenshot_path = screenshot_name("ozon", query)
                        page.screenshot(path=screenshot_path)
                        html_path = screenshot_path.replace(".png", ".html")
                        Path(html_path).write_text(page.content(), encoding="utf-8")
                        log("[ENGINE OZON]", "Диагностика сохранена: " + screenshot_path + " и " + html_path)

                    seen_urls = set()
                    for card in cards:
                        try:
                            href = card.get_attribute("href")
                            if not href or href in seen_urls:
                                continue
                            seen_urls.add(href)

                            text = card.text_content(timeout=1000) or ""
                            price = extract_price_ru(text)
                            card_title = extract_title_generic(text)
                            image_url = extract_image_url(card)

                            if price > 0:
                                if href.startswith("http"):
                                    full_url = href
                                else:
                                    full_url = "https://www.ozon.ru" + href
                                results.append({
                                    "platform": "Ozon",
                                    "title": card_title,
                                    "price": price,
                                    "url": full_url,
                                    "image_url": image_url,
                                    "location": None,
                                })
                        except Exception as card_err:
                            log("[ENGINE OZON]", "Пропущена карточка: " + str(card_err))
                            continue
                finally:
                    # Раньше при исключении между launch() и browser.close() браузер
                    # мог не закрыться корректно - теперь закрываем гарантированно.
                    if browser is not None:
                        browser.close()
        except Exception as e:
            log("[ENGINE OZON]", "Критический сбой Playwright: " + str(e))

        log("[ENGINE OZON]", "Найдено офферов: " + str(len(results)))
        return results


# ==========================================
# AVITO
# ==========================================
class AvitoScraper(BaseScraper):
    def search(self, query):
        results = []
        encoded_query = urllib.parse.quote(query)
        url = "https://www.avito.ru/" + config.AVITO_REGION_SLUG + "?q=" + encoded_query
        log("[ENGINE AVITO]", "Старт сканирования: " + url)

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=config.HEADLESS)
                context = browser.new_context(
                    user_agent=USER_AGENT,
                    viewport={"width": 1440, "height": 900},
                    locale="ru-RU",
                )
                page = context.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=45000)
                page.wait_for_timeout(2000)

                log("[ENGINE AVITO]", "Заголовок страницы: " + repr(page.title()))
                log("[ENGINE AVITO]", "Итоговый URL: " + page.url)

                blocked = page.locator("text=/доступ ограничен|подтвердите, что вы не робот/i").count() > 0
                if blocked:
                    log("[ENGINE AVITO]", "Похоже на антибот-заглушку Avito.")

                try:
                    page.wait_for_selector('[data-marker="item"]', timeout=15000)
                except Exception:
                    screenshot_path = screenshot_name("avito", query)
                    page.screenshot(path=screenshot_path)
                    log("[ENGINE AVITO]", "Карточки не появились. Скриншот: " + screenshot_path)
                    browser.close()
                    return results

                # Несколько шагов скролла, чтобы у карточек ниже экрана
                # успели подгрузиться настоящие картинки (lazy-load)
                scroll_to_load(page, steps=8, pause_ms=350)

                cards = page.locator('[data-marker="item"]').all()[:50]
                skipped_by_title_filter = 0

                for card in cards:
                    try:
                        card_title = "Товар Avito"
                        title_el = card.locator('[itemprop="name"]')
                        if title_el.count() > 0:
                            raw = title_el.first.text_content(timeout=1000)
                            if raw:
                                card_title = raw.strip()

                        if config.AVITO_TITLE_ONLY:
                            if not title_matches_query(card_title, query):
                                skipped_by_title_filter += 1
                                continue

                        price = 0.0
                        price_el = card.locator('[data-marker="item-price"]')
                        if price_el.count() > 0:
                            raw_price = price_el.first.text_content(timeout=1000) or ""
                            digits = "".join(c for c in raw_price if c.isdigit())
                            if digits:
                                price = float(digits)

                        link_el = card.locator('a[data-marker="item-title"]')
                        if link_el.count() > 0:
                            href = link_el.first.get_attribute("href")
                        else:
                            href = None

                        if not href:
                            continue

                        if href.startswith("http"):
                            full_url = href
                        else:
                            full_url = "https://www.avito.ru" + href

                        image_url = extract_image_url(card)

                        location = None
                        try:
                            parsed = urllib.parse.urlparse(full_url)
                            path_parts = [p for p in parsed.path.split("/") if p]
                            if path_parts:
                                city_slug = path_parts[0]
                                if city_slug != config.AVITO_REGION_SLUG:
                                    location = humanize_slug(city_slug)
                        except Exception:
                            location = None

                        if price > 0:
                            results.append({
                                "platform": "Avito",
                                "title": card_title,
                                "price": price,
                                "url": full_url,
                                "image_url": image_url,
                                "location": location,
                            })
                    except Exception as card_err:
                        log("[ENGINE AVITO]", "Пропущена карточка: " + str(card_err))
                        continue

                if config.AVITO_TITLE_ONLY and skipped_by_title_filter > 0:
                    log("[ENGINE AVITO]", "Отфильтровано по несовпадению названия: " + str(skipped_by_title_filter))

                browser.close()
        except Exception as e:
            log("[ENGINE AVITO]", "Критический сбой Playwright: " + str(e))

        log("[ENGINE AVITO]", "Найдено офферов: " + str(len(results)))
        return results


# ==========================================
# ALIEXPRESS.RU
# ==========================================
class AliExpressScraper(BaseScraper):
    def search(self, query):
        results = []
        encoded_query = urllib.parse.quote(query)
        url = "https://aliexpress.ru/wholesale?SearchText=" + encoded_query
        log("[ENGINE ALIEXPRESS]", "Старт сканирования: " + url)

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=config.HEADLESS)
                context = browser.new_context(
                    user_agent=USER_AGENT,
                    viewport={"width": 1440, "height": 900},
                    locale="ru-RU",
                    extra_http_headers={"Accept-Language": "ru-RU,ru;q=0.9"},
                )
                page = context.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=45000)
                page.wait_for_timeout(2000)
                scroll_to_load(page, steps=6, pause_ms=350)

                log("[ENGINE ALIEXPRESS]", "Заголовок страницы: " + repr(page.title()))
                log("[ENGINE ALIEXPRESS]", "Итоговый URL: " + page.url)

                cards = page.locator('a[href*="/item/"]').all()[:20]
                log("[ENGINE ALIEXPRESS]", "Найдено ссылок на товары: " + str(len(cards)))

                if len(cards) == 0:
                    screenshot_path = screenshot_name("aliexpress", query)
                    page.screenshot(path=screenshot_path)
                    log("[ENGINE ALIEXPRESS]", "Скриншот для диагностики: " + screenshot_path)

                seen_urls = set()
                for card in cards:
                    try:
                        href = card.get_attribute("href")
                        if not href or href in seen_urls:
                            continue
                        seen_urls.add(href)

                        text = card.text_content(timeout=1000) or ""
                        price = extract_price_ru(text)
                        card_title = extract_title_generic(text)
                        image_url = extract_image_url(card)

                        if price > 0:
                            if href.startswith("http"):
                                full_url = href
                            else:
                                full_url = "https://aliexpress.ru" + href
                            results.append({
                                "platform": "AliExpress",
                                "title": card_title,
                                "price": price,
                                "url": full_url,
                                "image_url": image_url,
                                "location": "за рубежом",
                            })
                    except Exception as card_err:
                        log("[ENGINE ALIEXPRESS]", "Пропущена карточка: " + str(card_err))
                        continue

                browser.close()
        except Exception as e:
            log("[ENGINE ALIEXPRESS]", "Критический сбой Playwright: " + str(e))

        log("[ENGINE ALIEXPRESS]", "Найдено офферов: " + str(len(results)))
        return results


class ScrapingEngine:
    def __init__(self):
        self.scrapers = [
            WildberriesScraper(),
            OzonScraper(),
            AvitoScraper(),
            AliExpressScraper(),
        ]

    def scan_all(self, query):
        aggregated_results = []
        last_index = len(self.scrapers) - 1
        for i, scraper in enumerate(self.scrapers):
            try:
                offers = scraper.search(query)
                aggregated_results.extend(offers)
            except Exception as e:
                scraper_name = scraper.__class__.__name__
                log("[ENGINE]", "Скрапер " + scraper_name + " упал целиком: " + str(e))
            if i < last_index:
                time.sleep(2)
        return aggregated_results
