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

TARGET_WARDS = ['渋谷区', '中央区', '目黒区', '品川区', '千代田区', '港区']

INUKI_WARD_SLUGS = {
    '渋谷区': 'shibuyaku',
    '中央区': 'chuoku',
    '目黒区': 'meguroku',
    '品川区': 'shinagawaku',
    '千代田区': 'chiyodaku',
    '港区': 'minatoku',
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


def _find_card(link):
    """リンク要素から物件カードのコンテナを探す"""
    card = link
    for _ in range(10):
        parent = card.parent
        if parent is None:
            break
        # カードらしき要素（div/article/li）で物件リンクが1つだけ含まれる場合
        if parent.name in ('div', 'article', 'li', 'section'):
            prop_links = parent.find_all('a', href=re.compile(r'/rent/\d+|/bukken/bukkens/\d+'))
            if len(prop_links) == 1:
                return parent
        card = parent
    return link


def _extract_rent(text):
    m = re.search(r'[\d.]+万円', text) or re.search(r'[\d,]+円', text)
    return m.group(0) if m else ''


def _extract_area(text):
    m = re.search(r'[\d.]+坪', text) or re.search(r'[\d.]+㎡', text) or re.search(r'[\d.]+m2', text)
    return m.group(0) if m else ''


def _extract_station(text):
    m = re.search(r'\S+駅[^\s　]*(?:徒歩\d+分)?', text)
    return m.group(0) if m else ''


# ─────────────────────────────────────────
# 居抜き市場 (inuki-ichiba.jp)
# ─────────────────────────────────────────

def scrape_inuki_ichiba():
    base = 'https://www.inuki-ichiba.jp'
    results = []

    for ward, slug in INUKI_WARD_SLUGS.items():
        page = 1
        while page <= 10:
            url = f'{base}/rent/{slug}' + (f'?page={page}' if page > 1 else '')
            try:
                resp = _get(url)
                soup = BeautifulSoup(resp.text, 'html.parser')

                # div.property_box が各物件カード
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

                    # タイトルは h3.title または最初のリンクテキスト
                    h = card.find(class_='title') or card.find(['h2', 'h3'])
                    title = h.get_text(strip=True) if h else link.get_text(strip=True)

                    # 賃料: "賃料" ラベルの直後の数字
                    rent = ''
                    rent_m = re.search(r'賃料\s*([\d,]+)\s*円', text)
                    if rent_m:
                        rent = rent_m.group(1).replace(',', '') + '円'

                    # 面積
                    area_m = re.search(r'([\d.]+)坪', text)
                    area = area_m.group(0) if area_m else _extract_area(text)

                    # 最寄り駅
                    station_m = re.search(r'(\S+駅)\s*徒歩(\d+)分', text)
                    station = f'{station_m.group(1)} 徒歩{station_m.group(2)}分' if station_m else ''

                    img = card.find('img')
                    img_src = img.get('src', '') if img else ''
                    if img_src and not img_src.startswith('http'):
                        img_src = base + img_src

                    results.append({
                        'id':        f'inuki-{m.group(1)}',
                        'title':     title,
                        'address':   ward,
                        'ward':      ward,
                        'rent':      rent,
                        'area':      area,
                        'station':   station,
                        'url':       base + link['href'],
                        'source':    '居抜き市場',
                        'image_url': img_src,
                    })

                # 次ページリンクがなければ終了
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
# 飲食店ドットコム (inshokuten.com)
# ─────────────────────────────────────────

# 対象区のregion番号 (調査済み)
INSHOKUTEN_REGIONS = {
    '港区':   4,
    '渋谷区': 6,
    '千代田区': 10,
    '中央区': 14,
    '品川区': 17,
    '目黒区': 22,
}


def _parse_inshokuten_card(card, base):
    """a.bukkenItemカードから物件情報を抽出する"""
    m = re.search(r'/bukken/bukkens/(\d+)', card.get('href', ''))
    if not m:
        return None

    title_tag = card.find(class_='bukkenItem__title')
    title = title_tag.get_text(strip=True) if title_tag else ''

    # テーブルから賃料・面積・最寄り駅・所在地を取得（1行にth+tdが複数ある場合も対応）
    rent = area = station = address = ''
    for tr in card.find_all('tr'):
        ths = tr.find_all('th')
        tds = tr.find_all('td')
        pairs = list(zip(ths, tds))
        for th, td in pairs:
            label = th.get_text(strip=True)
            value = td.get_text(' ', strip=True)
            if '賃料' in label:
                bold = td.find(class_='bold')
                rent = bold.get_text(strip=True) if bold else _extract_rent(value)
            elif '階数' in label or '面積' in label:
                area_m = re.search(r'([\d.]+)坪', value)
                area = area_m.group(0) if area_m else _extract_area(value)
            elif '最寄' in label:
                spans = [s.get_text(strip=True) for s in td.find_all('span', class_='bold')]
                if len(spans) >= 2:
                    mins = spans[1].rstrip('分')
                    station = f'{spans[0]}駅 徒歩{mins}分'
                else:
                    station_m = re.search(r'(\S+駅?)\s+徒歩\s*(\d+)分', value)
                    if station_m:
                        station = f'{station_m.group(1)} 徒歩{station_m.group(2)}分'
            elif '所在地' in label:
                address = value

    # 区名を所在地またはタイトルから取得
    ward = next((w for w in TARGET_WARDS if w in (address + title)), None)
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

    for ward, region in INSHOKUTEN_REGIONS.items():
        page = 1
        while page <= 10:
            if page == 1:
                url = f'{base}/bukken/kanto/bukkens/list/local-23ward/region-{region}/inuki/'
            else:
                url = f'{base}/bukken/kanto/bukkens/list/local-23ward/region-{region}/inuki/?page={page}'

            try:
                resp = _get(url)
                soup = BeautifulSoup(resp.text, 'html.parser')

                cards = soup.find_all('a', class_='bukkenItem')
                if not cards:
                    break

                for card in cards:
                    prop = _parse_inshokuten_card(card, base)
                    if prop:
                        results.append(prop)

                # 次ページ確認
                next_btn = soup.find('a', class_=re.compile(r'next|pagination.*next', re.I))
                if not next_btn:
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
# まとめて実行
# ─────────────────────────────────────────

def run_all():
    props = []
    props += scrape_inuki_ichiba()
    props += scrape_inshokuten()
    logger.info(f'合計: {len(props)}件取得')
    return props
