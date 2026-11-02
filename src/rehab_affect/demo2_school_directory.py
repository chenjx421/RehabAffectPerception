"""Read-only national school directory: region cascade, search and lookup.

The packaged data (``data/schools``, built by scripts/import_school_directory.py)
is loaded once per process. The five curated Qingpu public-source entries from
``school_directory`` keep their original ``directory_id`` and exact
city/district/name, so contexts saved before the national directory existed keep
the same derived ``school_id``. Approved manual schools come from the store's
``demo2_school_directory`` table and are passed in by the caller.

Nothing here is a tenant identity or permission grant; ``school_code`` is only a
stable directory key.
"""

from __future__ import annotations

import gzip
import json
import logging
import os
import re
import threading
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .school_directory import school_directory

DATA_DIR = Path(__file__).resolve().parent / "data" / "schools"
PAGE_SIZE = 20
MAX_PAGE = 500
QUERY_LIMIT = 50
SCHOOL_TYPES = ("特殊教育学校", "辅读学校", "小学", "初中", "九年一贯制", "中学", "高中", "职校")
# Curated public-source entries: Shanghai / Qingpu division codes.
_CURATED_CODES = {"province_code": "31", "city_code": "3101", "district_code": "310118"}
_CURATED_TYPES = {"特殊学校": "辅读学校"}
_TYPE_RANK = {"特殊教育学校": 0, "辅读学校": 0}
_LOGGER = logging.getLogger("rehab_affect.school_directory")
_LOCK = threading.Lock()
_DATASET: "_Dataset | None" = None


class DirectoryQueryError(ValueError):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code = code
        self.status = status


@dataclass
class _Dataset:
    regions: list[dict[str, Any]]
    region_index: dict[str, dict[str, Any]]
    parents: dict[str, str]
    entries: list[dict[str, Any]]
    by_code: dict[str, dict[str, Any]]
    manifest: dict[str, Any]
    sources: dict[str, dict[str, Any]]


def fold(text: Any) -> str:
    return unicodedata.normalize("NFKC", str(text or "")).casefold().strip()


def _read_gz(path: Path) -> Any:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return json.load(handle)


def _curated_entries() -> list[dict[str, Any]]:
    rows = []
    for entry in school_directory()["entries"]:
        rows.append({
            **entry, **_CURATED_CODES, "school_code": entry["directory_id"],
            "school_type": _CURATED_TYPES.get(entry["school_type"], entry["school_type"]),
            "origin": "curated", "initials": "", "region_basis": "source",
        })
    return rows


def _load(data_dir: Path = DATA_DIR) -> _Dataset:
    regions = _read_gz(data_dir / "regions.json.gz") if (data_dir / "regions.json.gz").exists() else []
    manifest = json.loads((data_dir / "manifest.json").read_text(encoding="utf-8")) if (data_dir / "manifest.json").exists() else {}
    sources = {item["source_id"]: item for item in manifest.get("sources", [])}
    region_index: dict[str, dict[str, Any]] = {}
    parents: dict[str, str] = {}
    for province in regions:
        region_index[province["code"]] = province
        for city in province["children"]:
            region_index[city["code"]] = city
            parents[city["code"]] = province["code"]
            for district in city["children"]:
                region_index[district["code"]] = district
                parents[district["code"]] = city["code"]
    curated = _curated_entries()
    taken = {(row["district"], row["school_name"]) for row in curated}
    entries = list(curated)
    for province in regions:
        path = data_dir / f"{province['code']}.json.gz"
        if not path.exists():
            continue
        for row in _read_gz(path).get("entries", []):
            if (row["district"], row["school_name"]) in taken:
                continue
            source = sources.get(row.get("source_id"), {})
            entries.append({
                "directory_id": row["school_code"], "school_code": row["school_code"],
                "school_name": row["school_name"], "province": row["province"], "city": row["city"],
                "district": row["district"], "province_code": row["province_code"],
                "city_code": row["city_code"], "district_code": row["district_code"],
                "school_type": row["school_type"], "initials": row.get("initials", ""),
                "street": None, "address": row.get("address"),
                "address_status": "public_source" if row.get("address") else "pending",
                "source_status": "directory", "source_url": source.get("url") or None,
                "source_title": source.get("title") or "全国学校目录",
                "source_published_on": None, "source_checked_on": row.get("updated_on"),
                "source_note": source.get("note") or "公开数据汇编，待核验。",
                "origin": "national", "region_basis": row.get("region_basis", "source"),
            })
    for row in entries:
        row["_name"] = fold(row["school_name"])
        row["_region"] = fold(row["province"] + row["city"] + row["district"])
    by_code = {row["directory_id"]: row for row in entries}
    return _Dataset(regions, region_index, parents, entries, by_code, manifest, sources)


def dataset() -> _Dataset:
    global _DATASET
    if _DATASET is None:
        with _LOCK:
            if _DATASET is None:
                _DATASET = _load()
    return _DATASET


def warm_up_in_background() -> threading.Thread | None:
    """Load the national directory off the request path at server start.

    The first load reads ~30 compressed province files; on slow disks this
    took longer than the page's 20 s request timeout, so the first teacher
    after a restart saw "请求超时".  Requests arriving during warm-up wait on
    ``_LOCK`` for the same load instead of starting another one.  Set
    ``REHAB_DEMO2_SCHOOL_DIRECTORY_WARMUP=0`` to keep loading lazy.
    """
    if os.getenv("REHAB_DEMO2_SCHOOL_DIRECTORY_WARMUP", "1") == "0" or _DATASET is not None:
        return None

    def _run() -> None:
        started = time.monotonic()
        try:
            data = dataset()
        except Exception as exc:  # the lazy path still retries on the first request
            _LOGGER.warning("school directory warm-up failed: %s", type(exc).__name__)
            return
        _LOGGER.info("school directory warm-up done: entries=%d duration_ms=%d",
                     len(data.entries), int((time.monotonic() - started) * 1000))

    thread = threading.Thread(target=_run, name="school-directory-warmup", daemon=True)
    thread.start()
    return thread


def reset_cache() -> None:
    """Tests / importer: re-read the packaged data on next use."""
    global _DATASET
    with _LOCK:
        _DATASET = None


def _region_label(row: dict[str, Any]) -> str:
    parts = [row.get("province") or "", row.get("city") or "", row.get("district") or ""]
    return "".join(part for i, part in enumerate(parts) if part and part not in parts[:i])


def public_entry(row: dict[str, Any]) -> dict[str, Any]:
    """Wire shape: no internal folding keys, no school_id (entries are not identities)."""
    item = {key: value for key, value in row.items() if not key.startswith("_") and key not in {"initials", "origin"}}
    item["origin"] = row.get("origin", "national")
    item["region_label"] = _region_label(row)
    return item


def region_children(parent: str = "") -> list[dict[str, Any]]:
    data = dataset()
    parent = str(parent or "").strip()
    if not parent:
        nodes = data.regions
    else:
        if not re.fullmatch(r"\d{2}|\d{4}", parent) or parent not in data.region_index:
            raise DirectoryQueryError("invalid_region", "地区编码无效，请重新选择")
        nodes = data.region_index[parent]["children"]
    level = {0: "province", 2: "city", 4: "district"}[len(parent)]
    return [{"code": node["code"], "name": node["name"], "level": level,
             "has_children": bool(node.get("children"))} for node in nodes]


def region_path(code: str) -> list[dict[str, str]]:
    data = dataset()
    path = []
    while code and code in data.region_index:
        path.insert(0, {"code": code, "name": data.region_index[code]["name"]})
        code = data.parents.get(code, "")
    return path


def resolve_region_codes(province_code: Any, city_code: Any, district_code: Any) -> dict[str, str] | None:
    """Codes from the cascade -> context names; ``None`` if they do not nest."""
    data = dataset()
    codes = [str(value or "") for value in (province_code, city_code, district_code)]
    if not (re.fullmatch(r"\d{2}", codes[0]) and re.fullmatch(r"\d{4}", codes[1]) and re.fullmatch(r"\d{6}", codes[2])):
        return None
    if data.parents.get(codes[1]) != codes[0] or data.parents.get(codes[2]) != codes[1]:
        return None
    province, city, district = (data.region_index[c]["name"] for c in codes)
    if city.endswith("直辖县级行政区划"):
        city = district
    return {"province": province, "city": city, "district": district,
            "province_code": codes[0], "city_code": codes[1], "district_code": codes[2]}


def find_entry(directory_id: Any) -> dict[str, Any] | None:
    if not isinstance(directory_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", directory_id):
        return None
    row = dataset().by_code.get(directory_id)
    return public_entry(row) if row else None


def coverage() -> dict[str, Any]:
    data = dataset()
    manifest = data.manifest
    special = sum(manifest.get("per_type", {}).get(t, 0) for t in ("特殊教育学校", "辅读学校"))
    total = len(data.entries)
    return {
        "kind": "national", "complete": False, "entry_count": total,
        "province_count": len({row["province_code"] for row in data.entries}),
        "special_education_count": special, "updated_on": manifest.get("updated_on"),
        "label": f"全国学校目录：收录 {total} 所学校，覆盖 {len(data.regions)} 个省级行政区；"
                 "特殊教育学校收录不完整，查不到可手动填写，管理员审核后归入目录。",
        "sources": [{"title": s.get("title"), "url": s.get("url"), "license": s.get("license"),
                     "retrieved_on": s.get("retrieved_on")} for s in data.sources.values()],
        "types": list(SCHOOL_TYPES),
    }


def _validate(q: Any, province: Any, city: Any, district: Any, school_type: Any, page: Any, scope: Any) -> dict[str, Any]:
    q = fold(q)
    if len(q) > QUERY_LIMIT or any(unicodedata.category(c).startswith("C") for c in q):
        raise DirectoryQueryError("invalid_query", f"搜索词最多 {QUERY_LIMIT} 个字符")
    codes = {}
    for key, value, pattern in (("province", province, r"\d{2}"), ("city", city, r"\d{4}"), ("district", district, r"\d{6}")):
        value = str(value or "").strip()
        if value and not re.fullmatch(pattern, value):
            raise DirectoryQueryError("invalid_region", "地区编码无效，请重新选择")
        codes[key] = value
    if codes["city"] and codes["province"] and not codes["city"].startswith(codes["province"]):
        raise DirectoryQueryError("invalid_region", "城市不属于所选省份")
    if codes["district"] and codes["city"] and dataset().parents.get(codes["district"]) not in {codes["city"], None}:
        raise DirectoryQueryError("invalid_region", "区县不属于所选城市")
    school_type = str(school_type or "").strip()
    if school_type and school_type not in SCHOOL_TYPES:
        raise DirectoryQueryError("invalid_type", "学校类型无效")
    try:
        page = 1 if page is None or page == "" else int(page)
    except (TypeError, ValueError):
        raise DirectoryQueryError("invalid_page", "页码无效") from None
    if not 1 <= page <= MAX_PAGE:
        raise DirectoryQueryError("invalid_page", "页码无效")
    scope = str(scope or "national").strip()
    if scope not in {"national", "public_source"}:
        raise DirectoryQueryError("invalid_scope", "学校来源无效")
    return {"q": q, **codes, "type": school_type, "page": page, "scope": scope}


def search(q: Any = "", *, province: Any = "", city: Any = "", district: Any = "", school_type: Any = "",
           page: Any = 1, scope: Any = "national", extra: Iterable[dict[str, Any]] = ()) -> dict[str, Any]:
    """Fuzzy name search (all whitespace-separated terms must match name or region;
    an ASCII term may also match pinyin initials). Region is optional."""
    params = _validate(q, province, city, district, school_type, page, scope)
    data = dataset()
    pool: list[dict[str, Any]] = list(data.entries)
    if params["scope"] == "public_source":
        pool = [row for row in pool if row.get("origin") == "curated"]
    else:
        for row in extra:
            pool.append({**row, "_name": fold(row["school_name"]),
                         "_region": fold(row["province"] + row["city"] + row["district"])})
    terms = [term for term in params["q"].split() if term]
    hits = []
    for row in pool:
        if params["province"] and row["province_code"] != params["province"]:
            continue
        if params["city"] and row["city_code"] != params["city"]:
            continue
        if params["district"] and row["district_code"] != params["district"]:
            continue
        if params["type"] and row["school_type"] != params["type"]:
            continue
        name_hits = 0
        matched = True
        for term in terms:
            if term in row["_name"]:
                name_hits += 1
            elif term.isascii() and term.isalpha() and row.get("initials", "").startswith(term):
                name_hits += 1
            elif term in row["_region"]:
                continue
            else:
                matched = False
                break
        if not matched:
            continue
        rank = (
            0 if row.get("origin") == "curated" else 1,
            0 if terms and name_hits == len(terms) else 1,
            0 if terms and row["_name"].startswith(terms[0]) else 1,
            _TYPE_RANK.get(row["school_type"], 1),
            row["province_code"], row["city_code"], row["district_code"], row["school_name"],
        )
        hits.append((rank, row))
    hits.sort(key=lambda item: item[0])
    total = len(hits)
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    start = (params["page"] - 1) * PAGE_SIZE
    items = [public_entry(row) for _, row in hits[start:start + PAGE_SIZE]]
    return {
        "items": items, "total": total, "page": params["page"], "page_size": PAGE_SIZE,
        "total_pages": total_pages,
        "filters": {k: params[k] for k in ("province", "city", "district", "type", "scope")},
        "query_length": len(params["q"]),
        "query_initials": bool(params["q"]) and params["q"].replace(" ", "").isascii() and params["q"].replace(" ", "").isalpha(),
    }
