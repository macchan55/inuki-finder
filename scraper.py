import re
import time
import logging

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/120.0.0.0 Safari/537.36'
    ),
    'Accept-Language': 'ja,en-US;q=0.9,en;q=0.8',
}

# ─────────────────────────────────────────
# エリア定義
# UI上のグループ名 → 実際の区・県名リスト
# ─────────────────────────────────────────

# UIで表示するチェックボックス用グループ
AREA_GROUPS = {
    '港区':      ['港区'],
    '目黒区':    ['目黒区'],
    '渋谷区':    ['渋谷区'],
    '世田谷区':  ['世田谷区'],
    '品川区':    ['品川区'],
    '中央区':    ['中央区'],
    '千代田区':  ['千代田区'],
    '豊島区':    ['豊島区'],
    'その他23区': [
        '新宿区', '文京区', '台東区', '墨田区', '江東区',
        '大田区', '中野区', '杉並区', '北区', '荒川区',
        '板橋区', '練馬区', '足立区', '葛飾区', '江戸川区',
    ],
    '神奈川県':  ['神奈川県'],
    '千葉県':    ['千葉県'],
    '埼玉県':    ['埼玉県'],
    '山梨県':    ['山梨県'],
    '大阪 北区':   ['大阪市北区'],
    '大阪 中央区': ['大阪市中央区'],
    '大阪 西区':   ['大阪市西区'],
    '大阪 福島区': ['大阪市福島区'],
    '大阪 その他': [
        '大阪市都島区', '大阪市此花区', '大阪市港区', '大阪市大正区',
        '大阪市天王寺区', '大阪市浪速区', '大阪市西淀川区', '大阪市東淀川区',
        '大阪市東成区', '大阪市生野区', '大阪市旭区', '大阪市城東区',
        '大阪市阿倍野区', '大阪市住吉区', '大阪市東住吉区', '大阪市西成区',
        '大阪市淀川区', '大阪市鶴見区', '大阪市住之江区', '大阪市平野区',
    ],
}

# ward値 → UIグループ名 の逆引き
WARD_TO_GROUP = {}
for _grp, _wards in AREA_GROUPS.items():
    for _w in _wards:
        WARD_TO_GROUP[_w] = _grp

# 長い区名（例: 大阪市港区）を短い区名（例: 港区）より先に判定させるため長さ降順にする
# （東京都港区と大阪市港区のように部分文字列が重複するケースの誤判定を防ぐ）
ALL_WARDS = sorted(
    [w for wards in AREA_GROUPS.values() for w in wards],
    key=len, reverse=True,
)

# ─────────────────────────────────────────
# 居抜き市場 スラグマップ
# ─────────────────────────────────────────
INUKI_ICHIBA_SLUGS = {
    '千代田区': 'chiyodaku',
    '中央区':   'chuoku',
    '港区':     'minatoku',
    '新宿区':   'shinjukuku',
    '文京区':   'bunkyoku',
    '台東区':   'taitoku',
    '墨田区':   'sumidaku',
    '江東区':   'kotoku',
    '品川区':   'shinagawaku',
    '目黒区':   'meguroku',
    '大田区':   'otaku',
    '世田谷区': 'setagayaku',
    '渋谷区':   'shibuyaku',
    '中野区':   'nakanoku',
    '杉並区':   'suginamiku',
    '豊島区':   'toshimaku',
    '北区':     'kitaku',
    '荒川区':   'arakawaku',
    '板橋区':   'itabashiku',
    '練馬区':   'nerimaku',
    '足立区':   'adachiku',
    '葛飾区':   'katsushikaku',
    '江戸川区': 'edogawaku',
    # 神奈川・千葉・埼玉は都市レベルスラグで代表取得
    '神奈川県': 'yokohamashi-nishiku',
    '千葉県':   'chibashi-chuoku',
    '埼玉県':   'saitamashi-omiyaku',
}

# ─────────────────────────────────────────
# 飲食店.com エリアスラグ
# 値は (リージョン, エリアスラグ, 区コード) の3要素タプル
# 区コードがNoneの場合はエリア全体を一括取得する
# ─────────────────────────────────────────
INSHOKUTEN_AREAS = {
    '港区':     ('kanto', 'local-23ward', 4),
    '渋谷区':   ('kanto', 'local-23ward', 6),
    '千代田区': ('kanto', 'local-23ward', 10),
    '中央区':   ('kanto', 'local-23ward', 14),
    '品川区':   ('kanto', 'local-23ward', 17),
    '目黒区':   ('kanto', 'local-23ward', 22),
    '世田谷区': ('kanto', 'local-23ward', 30),
    '豊島区':   ('kanto', 'local-23ward', 16),
    # その他23区は一括で取得
    'その他23区_all': ('kanto', 'local-23ward', None),
    '神奈川県': ('kanto', 'local-yokohama_kawasaki', None),
    '千葉県':   ('kanto', 'local-chiba', None),
    '埼玉県':   ('kanto', 'local-saitama', None),
    # 大阪
    '大阪市北区':   ('kansai', 'local-osaka', 235),
    '大阪市中央区': ('kansai', 'local-osaka', 236),
    '大阪市西区':   ('kansai', 'local-osaka', 216),
    '大阪市福島区': ('kansai', 'local-osaka', 214),
    'その他大阪_all': ('kansai', 'local-osaka', None),
}

# ─────────────────────────────────────────
# テンポスマート 区コード
# ─────────────────────────────────────────
TEMPOSMART_AREAS = {
    '千代田区': ('district', 13, 13101),
    '中央区':   ('district', 13, 13102),
    '港区':     ('district', 13, 13103),
    '新宿区':   ('district', 13, 13104),
    '文京区':   ('district', 13, 13105),
    '台東区':   ('district', 13, 13106),
    '墨田区':   ('district', 13, 13107),
    '江東区':   ('district', 13, 13108),
    '品川区':   ('district', 13, 13109),
    '目黒区':   ('district', 13, 13110),
    '大田区':   ('district', 13, 13111),
    '世田谷区': ('district', 13, 13112),
    '渋谷区':   ('district', 13, 13113),
    '中野区':   ('district', 13, 13114),
    '杉並区':   ('district', 13, 13115),
    '豊島区':   ('district', 13, 13116),
    '北区':     ('district', 13, 13117),
    '荒川区':   ('district', 13, 13118),
    '板橋区':   ('district', 13, 13119),
    '練馬区':   ('district', 13, 13120),
    '足立区':   ('district', 13, 13121),
    '葛飾区':   ('district', 13, 13122),
    '江戸川区': ('district', 13, 13123),
    '神奈川県': ('pref', 14, None),
    '千葉県':   ('pref', 12, None),
    '埼玉県':   ('pref', 11, None),
    '山梨県':   ('pref', 19, None),
    '大阪府':   ('pref', 27, None),
}

# ─────────────────────────────────────────
# テナントショップ 都道府県コード（pa番号）
# 「居抜き」フィルタ(f1=1)付きで都道府県単位に取得し、
# 区の振り分けは _detect_ward() に任せる
# 東京・神奈川・千葉・埼玉・山梨は実サイトで0件だったため対象外
# （pa番号は判明済み: 東京14/神奈川15/埼玉16/千葉17/山梨29。
#   将来このサイトに関東の掲載が増えたら追加できる）
# ─────────────────────────────────────────
TENANT_SHOP_PREFS = {
    '大阪府': 1,
}

# ─────────────────────────────────────────
# 居抜き本舗 スラグ
# ─────────────────────────────────────────
INUKI_HONPO_SLUGS = {
    '渋谷区':   'exul=115030',
    '中央区':   'exul=115065',
    '港区':     'exul=115008',
    '目黒区':   'exul=115012',
    '品川区':   'exul=115598',
    '千代田区': 'exul=115044',
    '世田谷区': 'exul=115013',
    '豊島区':   'exul=115019',
}


def _get(url, retries=2):
    for i in range(retries + 1):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            resp.raise_for_status()
            return resp
        except Exception as e:
            if i == retries:
                raise
            time.sleep(2)


def _extract_rent(text):
    m = re.search(r'[\d.]+万円', text) or re.search(r'[\d,]+円', text)
    return m.group(0) if m else ''


def _extract_area(text):
    m = re.search(r'[\d.]+坪', text) or re.search(r'[\d.]+㎡', text) or re.search(r'[\d.]+m2', text)
    return m.group(0) if m else ''


def _extract_station(text):
    m = re.search(r'\S+駅[^\s　]*(?:徒歩\d+分)?', text)
    return m.group(0) if m else ''


def _detect_ward(text):
    for w in ALL_WARDS:
        if w in text:
            return w
    return None


# ─────────────────────────────────────────
# 居抜き市場
# ─────────────────────────────────────────
def scrape_inuki_ichiba():
    base = 'https://www.inuki-ichiba.jp'
    results = []

    for ward, slug in INUKI_ICHIBA_SLUGS.items():
        page = 1
        while page <= 10:
            url = f'{base}/rent/{slug}' + (f'?page={page}' if page > 1 else '')
            try:
                resp = _get(url)
                soup = BeautifulSoup(resp.text, 'html.parser')
                cards = soup.find_all('div', class_='property_box')
                if not cards:
                    break

                for card in cards:
                    link = card.find('a', href=re.compile(r'^/rent/\d+'))
                    if not link:
                        continue
                    m = re.search(r'/rent/(\d+)', link['href'])
                    if not m:
                        continue

                    text = card.get_text(' ', strip=True)
                    h = card.find(class_='title') or card.find(['h2', 'h3'])
                    title = h.get_text(strip=True) if h else link.get_text(strip=True)

                    rent = ''
                    rent_m = re.search(r'賃料\s*([\d,]+)\s*円', text)
                    if rent_m:
                        rent = rent_m.group(1).replace(',', '') + '円'

                    area_m = re.search(r'([\d.]+)坪', text)
                    area = area_m.group(0) if area_m else _extract_area(text)

                    station_m = re.search(r'(\S+駅)\s*徒歩(\d+)分', text)
                    station = f'{station_m.group(1)} 徒歩{station_m.group(2)}分' if station_m else ''

                    img = card.find('img')
                    img_src = img.get('src', '') if img else ''
                    if img_src and not img_src.startswith('http'):
                        img_src = base + img_src

                    detected = _detect_ward(text) or ward
                    results.append({
                        'id':        f'inuki-{m.group(1)}',
                        'title':     title,
                        'address':   detected,
                        'ward':      detected,
                        'rent':      rent,
                        'area':      area,
                        'station':   station,
                        'url':       base + link['href'],
                        'source':    '居抜き市場',
                        'image_url': img_src,
                    })

                if not soup.find('a', string=re.compile(r'次|next', re.I)):
                    break
                page += 1
                time.sleep(1)

            except Exception as e:
                logger.error(f'居抜き市場 {ward} p{page}: {e}')
                break

        time.sleep(1.5)

    logger.info(f'居抜き市場: {len(results)}件')
    return results


# ─────────────────────────────────────────
# 飲食店.com
# ─────────────────────────────────────────
def _parse_inshokuten_card(card, base):
    m = re.search(r'/bukken/bukkens/(\d+)', card.get('href', ''))
    if not m:
        return None

    title_tag = card.find(class_='bukkenItem__title')
    title = title_tag.get_text(strip=True) if title_tag else ''

    rent = area = station = address = ''
    for tr in card.find_all('tr'):
        ths = tr.find_all('th')
        tds = tr.find_all('td')
        for th, td in zip(ths, tds):
            label = th.get_text(strip=True)
            value = td.get_text(' ', strip=True)
            if '賃料' in label:
                bold = td.find(class_='bold')
                rent = bold.get_text(strip=True) if bold else _extract_rent(value)
            elif '面積' in label:
                area_m = re.search(r'([\d.]+)坪', value)
                area = area_m.group(0) if area_m else _extract_area(value)
            elif '最寄' in label:
                spans = [s.get_text(strip=True) for s in td.find_all('span', class_='bold')]
                if len(spans) >= 2:
                    station = f'{spans[0]}駅 徒歩{spans[1].rstrip("分")}分'
                else:
                    sm = re.search(r'(\S+駅?)\s+徒歩\s*(\d+)分', value)
                    if sm:
                        station = f'{sm.group(1)} 徒歩{sm.group(2)}分'
            elif '所在地' in label:
                address = value

    ward = _detect_ward(address + title)
    if not ward:
        return None

    img = card.find('img')
    img_src = img.get('src', '') if img else ''
    if img_src and not img_src.startswith('http'):
        img_src = base + img_src

    return {
        'id':        f'inshokuten-{m.group(1)}',
        'title':     title,
        'address':   address or ward,
        'ward':      ward,
        'rent':      rent,
        'area':      area,
        'station':   station,
        'url':       base + card['href'],
        'source':    '飲食店.com',
        'image_url': img_src,
    }


def scrape_inshokuten():
    base = 'https://www.inshokuten.com'
    results = []
    seen_ids = set()

    for ward, (region, area_slug, region_code) in INSHOKUTEN_AREAS.items():
        page = 1
        while page <= 10:
            path = f'{area_slug}/' + (f'region-{region_code}/' if region_code else '')
            url = (f'{base}/bukken/{region}/bukkens/list/{path}inuki/'
                   + (f'?page={page}' if page > 1 else ''))
            try:
                resp = _get(url)
                soup = BeautifulSoup(resp.text, 'html.parser')
                cards = soup.find_all('a', class_='bukkenItem')
                if not cards:
                    break
                for card in cards:
                    prop = _parse_inshokuten_card(card, base)
                    if prop and prop['id'] not in seen_ids:
                        seen_ids.add(prop['id'])
                        results.append(prop)
                next_btn = soup.find('a', string=re.compile(r'次のページ|次へ|›|»'))
                if not next_btn:
                    break
                page += 1
                time.sleep(1.5)
            except Exception as e:
                logger.error(f'飲食店.com {ward} p{page}: {e}')
                break
        time.sleep(1)

    logger.info(f'飲食店.com: {len(results)}件')
    return results


# ─────────────────────────────────────────
# テンポスマート
# ─────────────────────────────────────────
def scrape_temposmart():
    base = 'https://www.temposmart.jp'
    results = []

    for ward, (kind, pref, district) in TEMPOSMART_AREAS.items():
        page = 1
        while page <= 10:
            if kind == 'district':
                base_url = f'{base}/estates/pref/{pref}/district/{district}?status=inuki'
            else:
                base_url = f'{base}/estates/pref/{pref}?status=inuki'
            url = base_url + (f'&page={page}' if page > 1 else '')

            try:
                resp = _get(url)
                soup = BeautifulSoup(resp.text, 'html.parser')
                cards = soup.find_all('li', class_='estatesMain__estateList--li')
                if not cards:
                    break

                for card in cards:
                    id_span = card.find(class_='estateItem__estateId--value')
                    prop_id_num = id_span.get_text(strip=True) if id_span else None
                    if not prop_id_num:
                        link = card.find('a', href=re.compile(r'/estates/\d+'))
                        if not link:
                            continue
                        mm = re.search(r'/estates/(\d+)', link['href'])
                        prop_id_num = mm.group(1) if mm else None
                    if not prop_id_num:
                        continue

                    h3 = card.find('h3', class_='estateItem__estateTitle')
                    title = h3.get_text(strip=True) if h3 else ''
                    if 'スケルトン' in title and '居抜き' not in title:
                        continue

                    text = card.get_text(' ', strip=True)
                    rent_m = re.search(r'賃料\s*([\d,]+)\s*円', text)
                    rent = rent_m.group(1).replace(',', '') + '円' if rent_m else _extract_rent(text)
                    area_m = re.search(r'面積\s*([\d.]+坪)', text)
                    area = area_m.group(1) if area_m else _extract_area(text)
                    station_m = re.search(r'最寄駅\s*(\S+駅)\s*徒歩\s*(\d+)分', text)
                    station = f'{station_m.group(1)} 徒歩{station_m.group(2)}分' if station_m else ''

                    detected = _detect_ward(text) or ward
                    img = card.find('img', attrs={'data-src': True})
                    img_src = img['data-src'] if img else ''

                    results.append({
                        'id':        f'temposmart-{prop_id_num}',
                        'title':     title,
                        'address':   detected,
                        'ward':      detected,
                        'rent':      rent,
                        'area':      area,
                        'station':   station,
                        'url':       f'{base}/estates/{prop_id_num}',
                        'source':    'テンポスマート',
                        'image_url': img_src,
                    })

                next_btn = soup.find('a', class_=re.compile(r'next', re.I))
                if not next_btn:
                    next_btn = soup.find('a', string=re.compile(r'次のページ|次へ|›'))
                if not next_btn:
                    break
                page += 1
                time.sleep(1.5)

            except Exception as e:
                logger.error(f'テンポスマート {ward} p{page}: {e}')
                break

        time.sleep(1)

    logger.info(f'テンポスマート: {len(results)}件')
    return results


# ─────────────────────────────────────────
# テナントショップ
# ─────────────────────────────────────────
def scrape_tenant_shop():
    base = 'https://www.tenant-shop.jp'
    results = []

    for label, pref_id in TENANT_SHOP_PREFS.items():
        page = 1
        while page <= 10:
            url = f'{base}/index.php?ac=2&c=12&pa={pref_id}&f1=1&p={page}'
            try:
                resp = _get(url)
                soup = BeautifulSoup(resp.text, 'html.parser')
                cards = soup.find_all('table', class_='result')
                if not cards:
                    break

                for card in cards:
                    link = card.find('a', href=re.compile(r'^/detail/e-\d+/'))
                    if not link:
                        continue
                    m = re.search(r'/detail/(e-\d+)/', link['href'])
                    if not m:
                        continue

                    title_tag = card.find(class_='estatename')
                    title = title_tag.get_text(strip=True) if title_tag else ''

                    price_tag = card.find(class_='price')
                    rent_raw = price_tag.get_text(strip=True) if price_tag else ''
                    rent_m = re.search(r'([\d.]+)万', rent_raw)
                    rent = f'{rent_m.group(1)}万円' if rent_m else ''

                    area_tag = card.find(class_='area_val')
                    area = area_tag.get_text(strip=True) if area_tag else ''

                    address = ''
                    station = ''
                    for add in card.find_all('div', class_='add'):
                        img = add.find('img')
                        src = img.get('src', '') if img else ''
                        txt = add.get_text(strip=True)
                        if 'addr' in src:
                            address = txt
                        elif 'station' in src:
                            station = txt

                    photo = card.find(class_='photo')
                    img_tag = photo.find('img') if photo else None
                    img_src = img_tag.get('src', '') if img_tag else ''
                    if img_src and not img_src.startswith('http'):
                        img_src = base + img_src

                    detected = _detect_ward(address + title) or label
                    results.append({
                        'id':        f'tenantshop-{m.group(1)}',
                        'title':     title,
                        'address':   address or detected,
                        'ward':      detected,
                        'rent':      rent,
                        'area':      area,
                        'station':   station,
                        'url':       f'{base}/detail/{m.group(1)}/',
                        'source':    'テナントショップ',
                        'image_url': img_src,
                    })

                page += 1
                time.sleep(1.5)

            except Exception as e:
                logger.error(f'テナントショップ {label} p{page}: {e}')
                break

        time.sleep(1)

    logger.info(f'テナントショップ: {len(results)}件')
    return results


# ─────────────────────────────────────────
# 居抜き本舗
# ─────────────────────────────────────────
def scrape_inuki_honpo():
    base = 'https://www.inuki-honpo.jp'
    results = []

    for ward, slug in INUKI_HONPO_SLUGS.items():
        page = 1
        while page <= 10:
            url = f'{base}/rent/{slug}/' + (f'?page={page}' if page > 1 else '')
            try:
                resp = _get(url)
                soup = BeautifulSoup(resp.text, 'html.parser')
                tables = soup.find_all('table', class_='bukkenListTable')
                if not tables:
                    break

                for table in tables:
                    link = table.find('a', href=re.compile(r'/rent/\d+'))
                    if not link:
                        continue
                    mm = re.search(r'/rent/(\d+)', link['href'])
                    if not mm:
                        continue

                    text = table.get_text(' ', strip=True)
                    title_tag = table.find(class_='bukkenListCat')
                    title = title_tag.get_text(strip=True) if title_tag else link.get_text(strip=True)
                    addr_m = re.search(r'[東京都]?[^\s　]{2,4}[区市町村][^\s　]*', text)
                    address = addr_m.group(0) if addr_m else ward
                    name_tag = table.find(class_='bukkenListName')
                    station = name_tag.get_text(strip=True) if name_tag else ''
                    rent_m = re.search(r'([\d,]+)\s*円', text)
                    rent = rent_m.group(1).replace(',', '') + '円' if rent_m else ''
                    area_m = re.search(r'([\d.]+)坪', text)
                    area = area_m.group(0) if area_m else _extract_area(text)
                    img = table.find('img', src=re.compile(r'\.(jpg|jpeg|png|webp)', re.I))
                    img_src = img.get('src', '') if img else ''
                    if img_src and not img_src.startswith('http'):
                        img_src = base + img_src

                    detected = _detect_ward(text) or ward
                    results.append({
                        'id':        f'honpo-{mm.group(1)}',
                        'title':     f'{detected} {title}',
                        'address':   address,
                        'ward':      detected,
                        'rent':      rent,
                        'area':      area,
                        'station':   station,
                        'url':       base + link['href'],
                        'source':    '居抜き本舗',
                        'image_url': img_src,
                    })

                next_btn = soup.find('a', string=re.compile(r'次のページ|次へ|NEXT|›'))
                if not next_btn:
                    break
                page += 1
                time.sleep(1.5)

            except Exception as e:
                logger.error(f'居抜き本舗 {ward} p{page}: {e}')
                break

        time.sleep(1)

    logger.info(f'居抜き本舗: {len(results)}件')
    return results


# ─────────────────────────────────────────
# まとめて実行
# ─────────────────────────────────────────
def run_all():
    props = []
    props += scrape_inuki_ichiba()
    props += scrape_inshokuten()
    props += scrape_temposmart()
    props += scrape_inuki_honpo()
    props += scrape_tenant_shop()
    logger.info(f'合計: {len(props)}件取得')
    return props
