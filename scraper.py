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

                # /rent/[数字] へのリンクを物件とみなす
                prop_links = soup.find_all('a', href=re.compile(r'^/rent/\d+'))
                if not prop_links:
                    break

                seen = set()
                for link in prop_links:
                    m = re.search(r'/rent/(\d+)', link['href'])
                    if not m or m.group(1) in seen:
                        continue
                    seen.add(m.group(1))

                    card = _find_card(link)
                    text = card.get_text(' ', strip=True)

                    h = card.find(['h2', 'h3', 'h4'])
                    title = h.get_text(strip=True) if h else text[:80]

                    img = card.find('img')
                    img_src = img.get('src', '') if img else ''
                    if img_src and not img_src.startswith('http'):
                        img_src = base + img_src

                    results.append({
                        'id':        f'inuki-{m.group(1)}',
                        'title':     title,
                        'address':   ward,
                        'ward':      ward,
                        'rent':      _extract_rent(text),
                        'area':      _extract_area(text),
                        'station':   _extract_station(text),
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

def scrape_inshokuten():
    base = 'https://www.inshokuten.com'
    results = []
    page = 1

    while page <= 20:
        if page == 1:
            url = f'{base}/bukken/kanto/bukkens/list/local-23ward/region-1/inuki/'
        else:
            url = f'{base}/bukken/kanto/bukkens/list/local-23ward/region-1/inuki/?page={page}'

        try:
            resp = _get(url)
            soup = BeautifulSoup(resp.text, 'html.parser')

            prop_links = soup.find_all('a', href=re.compile(r'/bukken/bukkens/\d+'))
            if not prop_links:
                break

            seen = set()
            for link in prop_links:
                m = re.search(r'/bukken/bukkens/(\d+)', link['href'])
                if not m or m.group(1) in seen:
                    continue
                seen.add(m.group(1))

                card = _find_card(link)
                text = card.get_text(' ', strip=True)

                # 対象区のみ保存
                ward = next((w for w in TARGET_WARDS if w in text), None)
                if not ward:
                    continue

                h = card.find(['h2', 'h3', 'h4'])
                title = h.get_text(strip=True) if h else text[:80]

                href = link['href']
                prop_url = base + href if href.startswith('/') else href

                img = card.find('img')
                img_src = img.get('src', '') if img else ''
                if img_src and not img_src.startswith('http'):
                    img_src = base + img_src

                results.append({
                    'id':        f'inshokuten-{m.group(1)}',
                    'title':     title,
                    'address':   ward,
                    'ward':      ward,
                    'rent':      _extract_rent(text),
                    'area':      _extract_area(text),
                    'station':   _extract_station(text),
                    'url':       prop_url,
                    'source':    '飲食店.com',
                    'image_url': img_src,
                })

            if not soup.find('a', string=re.compile(r'次のページ|次へ|›|»')):
                break
            page += 1
            time.sleep(1.5)

        except Exception as e:
            logger.error(f'飲食店.com p{page}: {e}')
            break

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
