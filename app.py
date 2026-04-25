import logging
import threading

from flask import Flask, jsonify, render_template, request
from apscheduler.schedulers.background import BackgroundScheduler

import database
import scraper

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

database.init_db()

TARGET_WARDS = ['渋谷区', '中央区', '目黒区', '品川区', '千代田区', '港区']

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
            database.upsert_property(p)
        logger.info(f'スクレイピング完了: {len(props)}件保存')
    except Exception as e:
        logger.error(f'スクレイピングエラー: {e}')
    finally:
        _scraping = False


# 毎朝8時に自動実行
scheduler = BackgroundScheduler(timezone='Asia/Tokyo')
scheduler.add_job(run_scrape, 'cron', hour=8, minute=0)
scheduler.start()

# 初回起動時にDBが空なら自動スクレイピング
if database.count_properties() == 0:
    t = threading.Thread(target=run_scrape, daemon=True)
    t.start()


@app.route('/')
def index():
    ward = request.args.get('ward', 'all')
    props = database.get_properties(ward)
    last_scraped = database.get_last_scraped()
    return render_template(
        'index.html',
        properties=props,
        wards=TARGET_WARDS,
        selected_ward=ward,
        last_scraped=last_scraped,
        scraping=_scraping,
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
