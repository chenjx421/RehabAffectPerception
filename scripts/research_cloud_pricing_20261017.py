"""Collect dated public pricing receipts; never access pilot credentials."""
import hashlib
import json
from pathlib import Path
import time

import requests
from bs4 import BeautifulSoup


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'output/cloud_research_20261017'
SOURCES = {
    'aliyun_ecs': 'https://www.aliyun.com/product/ecs',
    'aliyun_light': 'https://www.aliyun.com/product/swas',
    'aliyun_oss_storage': 'https://help.aliyun.com/zh/oss/product-overview/storage-fees',
    'aliyun_oss_traffic': 'https://help.aliyun.com/zh/oss/product-overview/traffic-fees',
    'aliyun_rds_pg': 'https://www.aliyun.com/product/rds/postgresql',
    'tencent_light': 'https://cloud.tencent.com/product/lighthouse',
    'tencent_cos': 'https://cloud.tencent.com/document/product/436/6239',
    'tencent_cos_traffic': 'https://cloud.tencent.com/document/product/436/33776',
    'tencent_pg': 'https://cloud.tencent.com/document/product/409/14163',
    'lightsail': 'https://aws.amazon.com/lightsail/pricing/',
    'aliyun_oss_calc': 'https://www.aliyun.com/price/product#/oss/detail/oss',
    'aliyun_domain': 'https://wanwang.aliyun.com/domain/com',
    'aliyun_ssl': 'https://help.aliyun.com/zh/ssl-certificate/product-overview/billing-overview',
    'letsencrypt': 'https://letsencrypt.org/getting-started/',
    'deepseek_price': 'https://api-docs.deepseek.com/zh-cn/quick_start/pricing',
    'cloudflare_quick': 'https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/trycloudflare/',
    'pg_security': 'https://www.postgresql.org/docs/current/ddl-rowsecurity.html',
    'tencent_pg_product': 'https://cloud.tencent.com/product/postgres',
    'tencent_pg_price': 'https://buy.cloud.tencent.com/price/pgsql',
    'tencent_cos_doc': 'https://cloud.tencent.com/document/product/436/53482',
    'tencent_cos_billing': 'https://cloud.tencent.com/document/product/436/16871',
    'tencent_domain': 'https://dnspod.cloud.tencent.com/?from=qcloudProductDns',
    'aliyun_domain_price': 'https://wanwang.aliyun.com/domain/price',
    'aliyun_price_oss': 'https://www.aliyun.com/price/product?spm=oss#/oss/detail/oss',
    'tencent_cos_js': 'https://cloudcache.tencent-cloud.com/qcloud/tea/app/cos-buy.zh.47dfd355e5.js',
    'aliyun_oss_price_detail': 'https://www.aliyun.com/price/detail/oss',
    'tencent_cos_traffic_doc': 'https://cloud.tencent.com/document/product/436/53863',
    'tencent_cos_requests_doc': 'https://cloud.tencent.com/document/product/436/53861',
    'tencent_pg_billing': 'https://cloud.tencent.com/document/product/409/49577',
    'tencent_pg_backup': 'https://cloud.tencent.com/document/product/409/88470',
}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    receipts_path = OUT / 'receipts.json'
    receipts = json.loads(receipts_path.read_text(encoding='utf-8')) if receipts_path.exists() else {}
    session = requests.Session()
    session.headers['User-Agent'] = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) CloudBudgetResearch/1.0'
    for key, url in SOURCES.items():
        if key in receipts:
            continue
        start = time.monotonic()
        item = {'id': key, 'url': url, 'accessed': '2026-10-17'}
        try:
            response = session.get(url, timeout=(8, 18))
            item.update(status=response.status_code, final_url=response.url,
                        sha256=hashlib.sha256(response.content).hexdigest())
            response.encoding = response.apparent_encoding or response.encoding
            soup = BeautifulSoup(response.text, 'html.parser')
            item['title'] = soup.title.get_text(' ', strip=True) if soup.title else ''
            for element in soup(['script', 'style', 'nav', 'footer', 'noscript']):
                element.decompose()
            text = soup.get_text('\n', strip=True)
            (OUT / (key + '.html')).write_bytes(response.content)
            (OUT / (key + '.txt')).write_text(text, encoding='utf-8')
            item['text_length'] = len(text)
        except Exception as exc:
            item['error_type'] = type(exc).__name__
        item['elapsed_sec'] = round(time.monotonic() - start, 2)
        receipts[key] = item
        print(json.dumps(item, ensure_ascii=True), flush=True)
        (OUT / 'receipts.json').write_text(json.dumps(receipts, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
