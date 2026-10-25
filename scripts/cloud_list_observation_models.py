"""Read model identifiers from the already configured endpoint; no image data."""
import http.client
import json
from pathlib import Path
import re
import ssl
import sys
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))


def main():
    from rehab_affect.demo2_observation_model import ObservationModelConfig
    config = ObservationModelConfig.from_env()
    if not config.enabled:
        raise ValueError('disabled')
    url = urlsplit(config.endpoint)
    path = url.path.removesuffix('/chat/completions') + '/models'
    connection = http.client.HTTPSConnection(url.hostname, url.port or 443, timeout=25,
                                            context=ssl.create_default_context())
    try:
        connection.request('GET', path, headers={'Authorization': 'Bearer ' + config.api_key,
                                                'Accept': 'application/json'})
        response = connection.getresponse()
        if response.status != 200:
            print(json.dumps({'ok': False, 'http_status': response.status}))
            return 1
        raw = response.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            raise ValueError('oversize')
        ids = [row.get('id') for row in json.loads(raw).get('data', []) if isinstance(row, dict)]
        ids = sorted(set(value for value in ids if isinstance(value, str)
            and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:/@-]{0,127}', value)))
        print(json.dumps({'ok': True, 'model_ids': ids[:100], 'capability_not_verified': True}))
        return 0
    finally:
        connection.close()


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception:
        print(json.dumps({'ok': False, 'error': 'model_catalog_unavailable'}))
        raise SystemExit(1)
