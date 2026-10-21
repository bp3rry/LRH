"""Fetch CC0 assets from Poly Haven (api.polyhaven.com) into assets/polyhaven/<id>/ as
.blend files with their textures, and record them in assets.lock.json.

Usage: python3 scripts/fetch_assets.py island_tree_01 jacaranda_tree ... [--res 1k]
"""

import hashlib
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOCK = ROOT / "assets.lock.json"
UA = {"User-Agent": "LRH-project/1.0 (asset fetch)"}


def get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=600) as r:
        return r.read()


def main():
    args = sys.argv[1:]
    res = "1k"
    if "--res" in args:
        res = args[args.index("--res") + 1]
        del args[args.index("--res"):args.index("--res") + 2]
    lock = json.loads(LOCK.read_text()) if LOCK.exists() else {"source": "Poly Haven (CC0)", "assets": {}}
    for aid in args:
        files = json.loads(get(f"https://api.polyhaven.com/files/{aid}"))
        info = json.loads(get(f"https://api.polyhaven.com/info/{aid}"))
        blend = files["blend"][res]["blend"]
        out = ROOT / "assets/polyhaven" / aid
        out.mkdir(parents=True, exist_ok=True)
        target = out / Path(blend["url"]).name
        data = get(blend["url"])
        target.write_bytes(data)
        for rel, inc in blend.get("include", {}).items():
            p = out / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(get(inc["url"]))
        lock["assets"][aid] = {"name": info.get("name"), "res": res, "file": str(target.relative_to(ROOT)),
                               "sha256": hashlib.sha256(data).hexdigest(), "licence": "CC0",
                               "url": f"https://polyhaven.com/a/{aid}",
                               "authors": list(info.get("authors", {}))}
        print(aid, round(len(data) / 1e6, 1), "MB")
    LOCK.write_text(json.dumps(lock, indent=1) + "\n")


if __name__ == "__main__":
    main()
