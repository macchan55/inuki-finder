import re

KEYWORD_SCORES = [
    (3, ['ワインセラー', 'ソムリエ', '会員制', 'VIPルーム', '完全個室', '掘りごたつ',
         '高級内装', '内装工事費', '造作譲渡', '高級店', '有名店', 'ミシュラン',
         '一棟', '邸宅', 'プライベートダイニング']),
    (2, ['個室', 'カウンター', 'ソファ', '照明', 'こだわり', '隠れ家', 'バー',
         '接待', '記念日', 'シャンデリア', 'テラス', 'ラウンジ', '石造り',
         '木製', '設計士', 'デザイナーズ', '大型厨房', '厨房設備充実']),
    (1, ['おしゃれ', 'スタイリッシュ', 'モダン', 'クラシック', '雰囲気',
         '落ち着い', '静か', '大人', 'リノベ', 'リフォーム済',
         '内装良好', '内装きれい', '内装綺麗', '内装良', '内装付き']),
]

MAX_KEYWORD_SCORE = 4.0
MAX_TSUBO_SCORE   = 3.0
MAX_TOTAL         = MAX_KEYWORD_SCORE + MAX_TSUBO_SCORE


def _keyword_score(text):
    if not text:
        return 0.0
    score = 0
    for pts, words in KEYWORD_SCORES:
        for w in words:
            if w in text:
                score += pts
    return min(score, MAX_KEYWORD_SCORE)


def _tsubo_price_score(tsubo_price):
    if tsubo_price is None:
        return 0.0
    if tsubo_price >= 40:
        return 3.0
    if tsubo_price >= 25:
        return 2.0
    if tsubo_price >= 15:
        return 1.0
    return 0.0


def compute_luxury_score(prop):
    text = ' '.join([
        prop.get('title', ''),
        prop.get('address', ''),
        prop.get('station', ''),
    ])

    rent_raw = prop.get('rent', '')
    area_raw = prop.get('area', '')
    tsubo_price = None

    rent_m = re.search(r'([\d,]+)\s*円', rent_raw.replace(' ', ''))
    area_m = re.search(r'([\d.]+)坪', area_raw)
    if not area_m:
        sqm_m = re.search(r'([\d.]+)㎡', area_raw)
        if sqm_m:
            tsubo_val = float(sqm_m.group(1)) / 3.3058
            if rent_m and tsubo_val > 0:
                rent_val = int(rent_m.group(1).replace(',', ''))
                tsubo_price = round(rent_val / tsubo_val / 10000, 1)
    else:
        tsubo_val = float(area_m.group(1))
        if rent_m and tsubo_val > 0:
            rent_val = int(rent_m.group(1).replace(',', ''))
            tsubo_price = round(rent_val / tsubo_val / 10000, 1)

    kw = _keyword_score(text)
    tp = _tsubo_price_score(tsubo_price)
    raw = kw + tp
    score = round(raw / MAX_TOTAL * 10, 1)
    return min(score, 10.0)
