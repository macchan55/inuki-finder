import re
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


def _parse_walk_minutes(station):
    if not station:
        return None
    m = re.search(r'徒歩(\d+)分', station)
    return int(m.group(1)) if m else None


def _parse_area_tsubo(area):
    if not area:
        return None
    m = re.search(r'([\d.]+)坪', area)
    if m:
        return float(m.group(1))
    m = re.search(r'([\d.]+)㎡', area)
    if m:
        return round(float(m.group(1)) / 3.3058, 2)
    return None


def _parse_rent_yen(rent):
    if not rent:
        return None
    cleaned = rent.replace(',', '').replace(' ', '')
    m = re.search(r'([\d]+)円', cleaned)
    if m:
        return int(m.group(1))
    m = re.search(r'([\d.]+)万', cleaned)
    if m:
        return int(float(m.group(1)) * 10000)
    return None


def get_properties(ward=None, limit=1000, max_walk=None, min_area=None, max_area=None, max_tsubo_price=None):
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

    result = []
    for row in rows:
        d = dict(row)
        walk = _parse_walk_minutes(d.get('station', ''))
        area = _parse_area_tsubo(d.get('area', ''))
        rent = _parse_rent_yen(d.get('rent', ''))

        d['walk_minutes'] = walk
        d['area_tsubo'] = area
        d['tsubo_price'] = round(rent / area / 10000, 1) if (rent and area and area > 0) else None

        if max_walk is not None and (walk is None or walk > max_walk):
            continue
        if min_area is not None and (area is None or area < min_area):
            continue
        if max_area is not None and area is not None and area > max_area:
            continue
        if max_tsubo_price is not None and d['tsubo_price'] is not None and d['tsubo_price'] > max_tsubo_price:
            continue

        result.append(d)

    return result


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
