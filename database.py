import sqlite3
from datetime import datetime

DB_PATH = "inuki.db"


def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS properties (
        id          TEXT PRIMARY KEY,
        title       TEXT,
        address     TEXT,
        ward        TEXT,
        rent        TEXT,
        area        TEXT,
        station     TEXT,
        url         TEXT,
        source      TEXT,
        image_url   TEXT,
        created_at  TEXT NOT NULL,
        fetched_at  TEXT NOT NULL
    )''')
    c.execute('CREATE INDEX IF NOT EXISTS idx_ward ON properties(ward)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_created ON properties(created_at DESC)')
    conn.commit()
    conn.close()


def upsert_property(prop):
    conn = sqlite3.connect(DB_PATH)
    now = datetime.now().isoformat()
    conn.execute('''
        INSERT INTO properties
            (id, title, address, ward, rent, area, station, url, source, image_url, created_at, fetched_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            title      = excluded.title,
            address    = excluded.address,
            rent       = excluded.rent,
            area       = excluded.area,
            station    = excluded.station,
            image_url  = excluded.image_url,
            fetched_at = excluded.fetched_at
    ''', (
        prop['id'], prop['title'], prop['address'], prop['ward'],
        prop['rent'], prop['area'], prop['station'], prop['url'],
        prop['source'], prop.get('image_url', ''), now, now
    ))
    conn.commit()
    conn.close()


def get_properties(ward=None, limit=300):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    if ward and ward != 'all':
        c.execute(
            'SELECT * FROM properties WHERE ward = ? ORDER BY created_at DESC LIMIT ?',
            (ward, limit)
        )
    else:
        c.execute('SELECT * FROM properties ORDER BY created_at DESC LIMIT ?', (limit,))
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_last_scraped():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT MAX(fetched_at) FROM properties')
    row = c.fetchone()
    conn.close()
    return row[0] if row and row[0] else None


def count_properties():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT COUNT(*) FROM properties')
    count = c.fetchone()[0]
    conn.close()
    return count
