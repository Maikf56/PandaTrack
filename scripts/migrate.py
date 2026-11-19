#!/usr/bin/env python3
"""迁移执行器：把 infra/migrations/{a,b} 升序应用到目标 PostgreSQL 库。

用法:
    python scripts/migrate.py --database a --url postgresql://pandatrack:PW@127.0.0.1:5432/pandatrack_a
幂等：迁移本身用 IF NOT EXISTS；执行前建 schema_migrations 表记录已应用文件。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--database", choices=["a", "b"], required=True)
    ap.add_argument("--url", required=True)
    args = ap.parse_args()

    try:
        import psycopg  # psycopg 3
    except ImportError:
        print("缺少 psycopg>=3：pip install 'psycopg[binary]'", file=sys.stderr)
        return 1

    mig_dir = ROOT / "infra" / "migrations" / args.database
    files = sorted(mig_dir.glob("*.sql"))
    if not files:
        print(f"无迁移文件: {mig_dir}", file=sys.stderr)
        return 1

    with psycopg.connect(args.url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations ("
                " filename TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())"
            )
            conn.commit()
            cur.execute("SELECT filename FROM schema_migrations")
            applied = {row[0] for row in cur.fetchall()}

            for f in files:
                if f.name in applied:
                    print(f"  = {args.database}/{f.name} 已应用，跳过")
                    continue
                sql = f.read_text(encoding="utf-8")
                cur.execute(sql)
                cur.execute(
                    "INSERT INTO schema_migrations (filename) VALUES (%s)", (f.name,)
                )
                conn.commit()
                print(f"  + {args.database}/{f.name} 应用成功")
    print(f"A/B 库 {args.database.upper()} 迁移完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
