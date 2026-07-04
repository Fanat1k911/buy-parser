import sqlite3
from datetime import datetime

DB_NAME = "monitor.db"


def init_db():
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS search_products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                query_name TEXT NOT NULL UNIQUE,
                target_price REAL NOT NULL,
                created_at TEXT NOT NULL,
                last_scanned_at TEXT,
                scan_interval_minutes INTEGER DEFAULT 60
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS found_offers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER,
                platform TEXT NOT NULL,
                title TEXT NOT NULL,
                price REAL NOT NULL,
                url TEXT NOT NULL UNIQUE,
                updated_at TEXT NOT NULL,
                image_url TEXT,
                location TEXT,
                FOREIGN KEY (product_id) REFERENCES search_products (id) ON DELETE CASCADE
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS price_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT NOT NULL,
                price REAL NOT NULL,
                recorded_at TEXT NOT NULL
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS notifications_sent (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT NOT NULL,
                price REAL NOT NULL,
                sent_at TEXT NOT NULL,
                UNIQUE(url, price)
            )
        ''')

        for stmt in [
            "ALTER TABLE search_products ADD COLUMN last_scanned_at TEXT",
            "ALTER TABLE search_products ADD COLUMN scan_interval_minutes INTEGER DEFAULT 60",
            "ALTER TABLE found_offers ADD COLUMN image_url TEXT",
            "ALTER TABLE found_offers ADD COLUMN location TEXT",
        ]:
            try:
                cursor.execute(stmt)
            except sqlite3.OperationalError:
                pass

        conn.commit()


def add_product(name, target_price, interval_minutes=60):
    try:
        with sqlite3.connect(DB_NAME) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO search_products (query_name, target_price, created_at, scan_interval_minutes) "
                "VALUES (?, ?, ?, ?)",
                (name, target_price, datetime.now().isoformat(), interval_minutes)
            )
            conn.commit()
            return True
    except sqlite3.IntegrityError:
        return False


def get_products():
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, query_name, target_price, last_scanned_at, scan_interval_minutes "
            "FROM search_products"
        )
        return cursor.fetchall()


def delete_product(prod_id):
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM search_products WHERE id = ?", (prod_id,))
        conn.commit()


def update_last_scanned(product_id):
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE search_products SET last_scanned_at = ? WHERE id = ?",
            (datetime.now().isoformat(), product_id)
        )
        conn.commit()


def update_scan_interval(product_id, minutes):
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE search_products SET scan_interval_minutes = ? WHERE id = ?",
            (minutes, product_id)
        )
        conn.commit()


def update_offers(product_id, offers):
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        now = datetime.now().isoformat()
        for offer in offers:
            image_url = offer.get("image_url")
            location = offer.get("location")
            cursor.execute('''
                INSERT INTO found_offers (product_id, platform, title, price, url, updated_at, image_url, location)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(url) DO UPDATE SET
                    price = excluded.price,
                    updated_at = excluded.updated_at,
                    image_url = excluded.image_url,
                    location = excluded.location
            ''', (product_id, offer['platform'], offer['title'], offer['price'], offer['url'], now, image_url,
                  location))

            cursor.execute(
                "INSERT INTO price_history (url, price, recorded_at) VALUES (?, ?, ?)",
                (offer['url'], offer['price'], now)
            )
        conn.commit()


def get_offers_for_product(product_id):
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT platform, title, price, url, updated_at, image_url, location
            FROM found_offers
            WHERE product_id = ?
            ORDER BY price ASC
        ''', (product_id,))
        return cursor.fetchall()


def get_price_history(url):
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT price, recorded_at FROM price_history WHERE url = ? ORDER BY recorded_at ASC",
            (url,)
        )
        return cursor.fetchall()


def was_notified(url, price):
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT 1 FROM notifications_sent WHERE url = ? AND price = ?",
            (url, price)
        )
        return cursor.fetchone() is not None


def mark_notified(url, price):
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR IGNORE INTO notifications_sent (url, price, sent_at) VALUES (?, ?, ?)",
            (url, price, datetime.now().isoformat())
        )
        conn.commit()
