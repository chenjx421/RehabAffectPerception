"""Import or incrementally update the packaged national school directory.

Examples (run with ``PYTHONPATH=src``)::

    # 1. Administrative divisions (国家统计局区划代码, modood/Administrative-divisions-of-China pca-code.json)
    uv run python scripts/import_school_directory.py regions --input pca-code.json

    # 2. Public POI school export: [{name, province, city, area, address, location}]
    uv run python scripts/import_school_directory.py schools --format baidu --input 中小学.json \
        --source-id poi-zsts119 --source-title "全国中小学公开地图数据集" \
        --source-url https://github.com/ZsTs119/china-university-database --retrieved-on 2026-10-31

    # 3. Overpass JSON of special schools; districts inferred from the nearest reference POI
    uv run python scripts/import_school_directory.py schools --format osm --input osm.json --reference 中小学.json ...

    # 4. Official list transcribed to CSV (学校名称,省,市,区县[,类型][,地址])
    uv run python scripts/import_school_directory.py schools --format csv --input 特殊教育学校名单.csv ...

Imports upsert by ``school_code``; entries from earlier sources stay. Every run
writes one ``directory_import`` line to school_debug_YYYYMMDD.jsonl (directory
from ``--log-dir`` or REHAB_DEMO2_SCHOOL_DEBUG_LOG_DIR, default .runtime/logs).
Exit codes: 0 = ok (including an unchanged re-import), 1 = no entries parsed, 2 = usage/input error.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from rehab_affect import school_directory_import as builder  # noqa: E402
from rehab_affect.demo2_school_debug import DEBUG_LOG_DIR_ENV, school_debug_event  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("command", choices=("regions", "schools", "manifest"))
    parser.add_argument("--input", type=Path)
    parser.add_argument("--format", choices=("baidu", "osm", "csv"), default="baidu")
    parser.add_argument("--reference", type=Path, help="baidu-format JSON used to infer OSM districts")
    parser.add_argument("--data-dir", type=Path, default=builder.DATA_DIR)
    parser.add_argument("--source-id", default="")
    parser.add_argument("--source-title", default="")
    parser.add_argument("--source-url", default="")
    parser.add_argument("--source-license", default="")
    parser.add_argument("--source-note", default="")
    parser.add_argument("--retrieved-on", default=time.strftime("%Y-%m-%d"))
    parser.add_argument("--log-dir", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if args.log_dir:
        os.environ[DEBUG_LOG_DIR_ENV] = str(args.log_dir)
    elif not os.getenv(DEBUG_LOG_DIR_ENV):
        os.environ[DEBUG_LOG_DIR_ENV] = str(ROOT / ".runtime" / "logs")
    started = time.monotonic()

    try:
        if args.command == "regions":
            if not args.input:
                parser.error("regions 需要 --input pca-code.json")
            tree = builder.build_regions(json.loads(args.input.read_text(encoding="utf-8")))
            if not args.dry_run:
                builder.write_regions(tree, args.data_dir)
                builder.write_manifest(None, args.data_dir)
            counts = {"provinces": len(tree), "received": sum(len(c["children"]) for p in tree for c in p["children"])}
            school_debug_event(None, "directory_import", "ok", source_id="regions", dry_run=args.dry_run,
                               duration_ms=int((time.monotonic() - started) * 1000), **counts)
            print(json.dumps({"ok": True, "command": "regions", **counts}, ensure_ascii=False))
            return 0
        if args.command == "manifest":
            manifest = builder.write_manifest(None, args.data_dir)
            print(json.dumps({"ok": True, "entry_count": manifest["entry_count"],
                              "province_count": manifest["province_count"]}, ensure_ascii=False))
            return 0
        if not args.input or not args.source_id or not args.source_title:
            parser.error("schools 需要 --input、--source-id 和 --source-title")
        source = builder.Source(args.source_id, args.source_title, args.source_url, args.source_license,
                                args.retrieved_on, args.source_note)
        regions = builder.RegionIndex(builder.load_regions(args.data_dir))
        if args.format == "csv":
            entries = builder.parse_csv(args.input, regions, source)
        else:
            payload = json.loads(args.input.read_text(encoding="utf-8"))
            if args.format == "baidu":
                entries = builder.parse_baidu(payload, regions, source)
            else:
                if not args.reference:
                    parser.error("osm 格式需要 --reference 用于推断区县")
                reference = json.loads(args.reference.read_text(encoding="utf-8"))
                entries = builder.parse_osm(payload, regions, source, reference)
        stats = builder.merge_entries(entries, source, args.data_dir, dry_run=args.dry_run)
    except (OSError, ValueError, KeyError) as exc:
        school_debug_event(None, "directory_import", "error", code=type(exc).__name__,
                           duration_ms=int((time.monotonic() - started) * 1000))
        print(json.dumps({"ok": False, "error": type(exc).__name__, "message": str(exc)[:300]}, ensure_ascii=False))
        return 2
    result = "ok" if stats["received"] else "empty"
    school_debug_event(None, "directory_import", result, source_id=args.source_id, dry_run=args.dry_run,
                       **{k: v for k, v in stats.items() if isinstance(v, int)})
    print(json.dumps({"ok": result == "ok", **stats}, ensure_ascii=False))
    return 0 if result == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
