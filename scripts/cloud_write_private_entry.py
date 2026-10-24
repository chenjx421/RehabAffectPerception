"""Create local private cloud invitation files without logging the secret URL."""
from pathlib import Path
from urllib.parse import quote
import html
import json

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / '.runtime/manager_share_config.json'
DESTINATION = ROOT / '.runtime/cloud_deploy_20261020'


def main():
    config = json.loads(CONFIG.read_text(encoding='utf-8-sig'))
    url = 'https://YOUR_SERVER_IP/invite#secret=' + quote(config['invite_secret'], safe='')
    files = {
        'cloud_invitation.private.txt': url + '\n',
        'open_cloud_demo.private.html': '<!doctype html><html lang="zh-CN"><meta charset="utf-8">'
            '<meta name="referrer" content="no-referrer"><title>Cloud Demo</title>'
            '<p><a href="' + html.escape(url, quote=True) + '">Open Cloud Demo</a></p>'
            '<script>location.replace(' + json.dumps(url) + ')</script></html>',
    }
    for name, content in files.items():
        path = DESTINATION / name
        if path.exists():
            if path.read_text(encoding='utf-8') != content:
                raise RuntimeError('Private invitation already exists with different content')
        else:
            with path.open('x', encoding='utf-8') as output:
                output.write(content)
    print(json.dumps({'ok': True, 'origin': 'https://YOUR_SERVER_IP',
        'private_entry_files_created': list(files), 'invitation_secret_preserved': True,
        'expires_at': config['expires_at']}))


if __name__ == '__main__':
    main()
