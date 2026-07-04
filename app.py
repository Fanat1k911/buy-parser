import pandas as pd
import streamlit as st

import config
import database as db
from scraper import ScrapingEngine, format_dt

db.init_db()
engine = ScrapingEngine()

st.set_page_config(page_title="Price Monitor SPb", layout="wide")
st.title("🛍️ Мониторинг цен (Санкт-Петербург)")
st.caption("Wildberries · Ozon · Avito · AliExpress — сравнение цен и уведомления в Telegram при снижении цены")

with st.sidebar:
    st.header("Добавить товар")
    new_product_name = st.text_input("Название товара (например, PlayStation 5)")
    target_price = st.number_input("Желаемая цена (руб)", min_value=0, value=40000)
    interval_minutes = st.number_input(
        "Интервал сканирования (мин)",
        min_value=1,
        value=config.DEFAULT_SCAN_INTERVAL_MINUTES,
    )

    if st.button("Запустить отслеживание"):
        if new_product_name:
            success = db.add_product(new_product_name, target_price, interval_minutes)
            if success:
                st.success("Товар '" + new_product_name + "' добавлен!")
                st.rerun()
            else:
                st.error("Этот товар уже отслеживается.")
        else:
            st.warning("Введите название.")

    st.divider()
    st.caption(
        "worker.py сканирует в фоне и шлёт уведомления в Telegram, у каждого товара свой "
        "интервал. Кнопка ниже — разовый ручной скан прямо из интерфейса."
    )

products = db.get_products()

if not products:
    st.info("Вы пока не добавили ни одного товара для отслеживания.")
else:
    for prod_id, name, t_price, last_scanned, interval_minutes in products:
        if last_scanned:
            scanned_label = "последний скан: " + format_dt(last_scanned)
        else:
            scanned_label = "ещё не сканировался"

        header = (
                "📋 " + name + " (Цель: " + format(t_price, ",.0f") + " руб., интервал: "
                + str(interval_minutes) + " мин.) — " + scanned_label
        )

        with st.expander(header, expanded=True):
            col1, col2 = st.columns([4, 1])

            with col2:
                if st.button("🗑️ Удалить", key="del_" + str(prod_id)):
                    db.delete_product(prod_id)
                    st.rerun()

                if st.button("🔄 Сканировать сейчас", key="scan_" + str(prod_id)):
                    with st.spinner("Опрашиваем площадки (Ozon/Avito/AliExpress могут занять до минуты)..."):
                        offers = engine.scan_all(name)
                        if offers:
                            db.update_offers(prod_id, offers)
                            db.update_last_scanned(prod_id)
                            st.success("Найдено офферов: " + str(len(offers)))
                            st.rerun()
                        else:
                            st.warning("Площадки не вернули результатов.")

                new_interval = st.number_input(
                    "Интервал (мин)",
                    min_value=1,
                    value=interval_minutes,
                    key="interval_" + str(prod_id),
                )
                if st.button("💾 Сохранить интервал", key="save_interval_" + str(prod_id)):
                    db.update_scan_interval(prod_id, new_interval)
                    st.success("Интервал обновлён.")
                    st.rerun()

            with col1:
                offers = db.get_offers_for_product(prod_id)
                if not offers:
                    st.write("*Данные ещё не собраны. Нажмите 'Сканировать сейчас'*")
                else:
                    for platform, title, price, url, updated_at, image_url, location in offers:
                        card = st.container(border=True)
                        with card:
                            img_col, info_col = st.columns([1, 5])

                            with img_col:
                                if image_url:
                                    st.image(image_url, width=80)
                                else:
                                    st.markdown("🖼️")

                            with info_col:
                                if price <= t_price:
                                    badge = "🔥"
                                else:
                                    badge = "🔹"

                                title_line = badge + " **[" + platform + "]** " + title
                                st.markdown(title_line)

                                price_line = "`" + format(price, ",.0f") + " руб.`"
                                if location:
                                    price_line += "  •  📦 доставка из: " + location
                                st.markdown(price_line)

                                meta_line = (
                                        "[Ссылка на товар](" + url + ") · обновлено: " + format_dt(updated_at)
                                )
                                st.caption(meta_line)

                        history = db.get_price_history(url)
                        if len(history) > 1:
                            df = pd.DataFrame(history, columns=["price", "recorded_at"])
                            df["recorded_at"] = pd.to_datetime(df["recorded_at"])
                            df = df.set_index("recorded_at")
                            with st.expander("📈 История цены — " + title[:40]):
                                st.line_chart(df["price"])
