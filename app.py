import logging
import threading

from flask import Flask, jsonify, render_template, request
from apscheduler.schedulers.background import BackgroundScheduler

import database
import scraper
import luxury
from scraper import AREA_GROUPS, WARD_TO_GROUP

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
database.init_db()

_scraping = False


def run_scrape():
    global _scraping
    if _scraping:
        logger.info('スクレイピング既に実行中のためスキップ')
        return
    _scraping = True
    try:
        logger.info('スクレイピング開始')
        props = scraper.run_all()
        for p in props:
            p['luxury_score'] = luxury.compute_luxury_score(p)
            database.upsert_property(p)
        logger.info(f'スクレイピング完了: {len(props)}件保存')
    except Exception as e:
        logger.error(f'スクレイピングエラー: {e}')
    finally:
        _scraping = False


scheduler = BackgroundScheduler(timezone='Asia/Tokyo')
scheduler.add_job(run_scrape, 'cron', hour=8, minute=0)
scheduler.start()


def _scrape_on_startup():
    if database.count_properties() == 0:
        logger.info('DBが空のため起動時スクレイピングを開始')
        t = threading.Thread(target=run_scrape, daemon=True)
        t.start()


_scrape_on_startup()


@app.route('/')
def index():
    # チェックボックスは複数選択可能（?areas=港区&areas=渋谷区 ...）
    selected_areas = request.args.getlist('areas')
    max_walk  = request.args.get('max_walk', type=int)
    min_area  = request.args.get('min_area', type=float)
    max_area  = request.args.get('max_area', type=float)
    max_tsubo = request.args.get('max_tsubo', type=int)
    min_luxury_val = request.args.get('min_luxury', type=float)
    sort_by   = request.args.get('sort_by', 'new')
    keyword   = request.args.get('keyword', '').strip()

    # 選択されたグループ名に対応するwardリストを展開
    target_wards = None
    if selected_areas:
        target_wards = []
        for grp in selected_areas:
            target_wards.extend(AREA_GROUPS.get(grp, [grp]))

    props = database.get_properties(
        wards=target_wards,
        max_walk=max_walk,
        min_area=min_area,
        max_area=max_area,
        max_tsubo_price=max_tsubo,
        min_luxury=min_luxury_val,
        sort_by='luxury' if sort_by == 'luxury' else None,
        keyword=keyword or None,
    )

    last_scraped = database.get_last_scraped()
    return render_template(
        'index.html',
        properties=props,
        area_groups=list(AREA_GROUPS.keys()),
        selected_areas=selected_areas,
        last_scraped=last_scraped,
        scraping=_scraping,
        empty_db=(database.count_properties() == 0),
        max_walk=max_walk or '',
        min_area=min_area or '',
        max_area=max_area or '',
        max_tsubo=max_tsubo or '',
        min_luxury=min_luxury_val or '',
        sort_by=sort_by,
        keyword=keyword,
    )


@app.route('/api/scrape', methods=['POST'])
def api_scrape():
    if _scraping:
        return jsonify({'status': 'already_running'})
    t = threading.Thread(target=run_scrape, daemon=True)
    t.start()
    return jsonify({'status': 'started'})


@app.route('/api/status')
def api_status():
    return jsonify({
        'scraping': _scraping,
        'count': database.count_properties(),
        'last_scraped': database.get_last_scraped(),
    })


if __name__ == '__main__':
    app.run(debug=True, port=5000)
