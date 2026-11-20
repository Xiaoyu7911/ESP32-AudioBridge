"""Check all release files without opening a serial or audio device."""
from pathlib import Path
import hashlib
import json

root = Path(__file__).resolve().parents[1]
count = 0
for line in (root / 'MANIFEST_SHA256.txt').read_text(encoding='utf-8').splitlines():
    expected, name = line.split('  ', 1)
    path = (root / name).resolve()
    if not path.is_relative_to(root) or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise SystemExit('Integrity check failed: ' + name)
    count += 1
for manifest_path in root.glob('prebuilt/*/manifest.json'):
    for item in json.loads(manifest_path.read_text())['images']:
        data = (manifest_path.parent / item['path']).read_bytes()
        if len(data) != item['bytes'] or hashlib.sha256(data).hexdigest() != item['sha256']:
            raise SystemExit('Firmware check failed: ' + item['path'])
print(f'PASS: {count} files verified; no hardware accessed.')
