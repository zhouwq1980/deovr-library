#!/usr/bin/env python3
"""空白项目冒烟测试：demo 扫描 + API 基本可用。"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    from fastapi.testclient import TestClient

    from deovr_lib.config import load_config
    from deovr_lib.db import Database
    from deovr_lib.server import create_app
    from run_cli import cmd_demo
    import argparse

    rc = cmd_demo(argparse.Namespace(serve=False, port=8765))
    if rc != 0:
        return rc

    db = Database()
    n = db.movie_count()
    assert n >= 3, f"expected >=3 demo movies, got {n}"

    app = create_app(db, load_config())
    c = TestClient(app)
    r = c.get("/browse")
    assert r.status_code == 200
    r = c.get("/deovr?format=json")
    assert r.status_code == 200
    data = r.json()
    assert data.get("scenes"), data
    r = c.get("/api/movies?page_size=10")
    assert r.json()["total"] >= 3
    print(f"smoke OK: movies={n}, scenes={len(data['scenes'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
