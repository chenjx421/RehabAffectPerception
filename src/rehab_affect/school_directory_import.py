"""Build and incrementally update the packaged national school directory.

Data layout (``src/rehab_affect/data/schools``):

* ``regions.json.gz``: province -> city -> district tree with statistical-division
  codes. Municipalities collapse their ``市辖区``/``县`` level into one city node
  named after the municipality, matching the stored school context
  (``city='上海市'``).
* ``<province_code>.json.gz``: ``{"province_code", "province", "entries": [...]}``.
* ``manifest.json``: sources, retrieval dates, counts per province and type.

Entries are directory metadata only. A ``school_code`` is a stable local key
derived from the resolved region code and the published name; it is not a
government school code, tenant ID or permission grant. Importing is an upsert by
``school_code``: existing entries from other sources are kept, so official lists
can be layered on later without losing earlier coverage.
"""

from __future__ import annotations

import csv
import gzip
import hashlib
import json
import math
import re
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Iterable

DATA_DIR = Path(__file__).resolve().parent / "data" / "schools"
MUNICIPALITIES = {"11", "12", "31", "50"}
SCHOOL_TYPES = ("特殊教育学校", "辅读学校", "小学", "初中", "九年一贯制", "中学", "高中", "职校")

_SPECIAL = re.compile(r"特殊教育学校|特教学校|特殊教育中心学校|培智|启智学校|启智中心|聋哑|聋人学校|聋校|盲人学校|盲校|盲聋|启聪学校|启明学校|启音学校|育智学校|康复学校|特殊学校")
_EXCLUDE = re.compile(r"大学|学院|幼儿园|幼稚园|托育|早教|培训|辅导|驾校|驾驶|党校|教育局|教育中心(?!学校)|研究院|研修|进修|成人|电大|开放大学|夜校|老年|艺术团|俱乐部|分部办公|招生|宿舍|食堂|体育场|运动场|停车场|门卫|[东西南北]门$|校区?门|教学楼|实验楼|图书馆")
_KEEP_DESPITE_EXCLUDE = re.compile(r"附属中学|附属小学|附属实验|附属学校|附中|附小")
_ZERO_WIDTH = re.compile(r"[​-‏‪-‮⁠﻿]")


def clean_text(value: Any, limit: int) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = _ZERO_WIDTH.sub("", text)
    text = "".join(ch for ch in text if not unicodedata.category(ch).startswith("C"))
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def classify_school(name: str) -> str | None:
    """Infer a coarse school stage from the published name; ``None`` = not a school."""
    if not name or len(name) < 3:
        return None
    if "辅读" in name:
        return "辅读学校"
    if _SPECIAL.search(name):
        if re.search(r"师范|职业学院|大学", name):
            return None
        return "特殊教育学校"
    if _EXCLUDE.search(name) and not _KEEP_DESPITE_EXCLUDE.search(name):
        return None
    if re.search(r"职业|职高|职校|技工|技师|中专|中等专业|卫生学校|卫校|职教中心|师范学校|艺术学校|体育运动学校|工业学校|商业学校|农业学校|财经学校|旅游学校", name):
        return "职校"
    if re.search(r"九年一贯|九年制|一贯制", name):
        return "九年一贯制"
    if re.search(r"小学|附小|小学校", name):
        return "小学"
    if re.search(r"初级中学|初中", name):
        return "初中"
    if re.search(r"高级中学|高中", name):
        return "高中"
    if re.search(r"中学|附中", name):
        return "中学"
    if re.search(r"(实验|外国语|双语|实验学|育才|学)校(\(|（|$)|学校(\(|（|$)", name):
        return "九年一贯制"
    return None


def school_code_for(region_code: str, province: str, city: str, district: str, name: str) -> str:
    digest = hashlib.sha256("|".join((province, city, district, name)).encode("utf-8")).hexdigest()[:10]
    return f"cn{region_code}-{digest}"


def name_initials(name: str) -> str:
    """Pinyin initials when ``pypinyin`` is importable at build time (runtime never needs it)."""
    try:
        from pypinyin import Style, lazy_pinyin  # type: ignore
    except ImportError:
        return ""
    letters = [part[0] for part in lazy_pinyin(name, style=Style.FIRST_LETTER, errors="ignore") if part]
    return "".join(letters).lower()[:40]


# --------------------------------------------------------------------------- regions

@dataclass
class RegionIndex:
    tree: list[dict[str, Any]]
    provinces: dict[str, dict[str, Any]] = field(default_factory=dict)  # name -> node

    def __post_init__(self) -> None:
        for province in self.tree:
            self.provinces[province["name"]] = province
            self.provinces[_short_province(province["name"])] = province

    def resolve(self, province: str, city: str, district: str) -> dict[str, str] | None:
        """Map free-text names to codes; returns context-ready names or ``None``."""
        node = self.provinces.get(province) or self.provinces.get(_short_province(province))
        if node is None:
            return None
        city_node = None
        if node["code"] in MUNICIPALITIES:
            city_node = node["children"][0]
        else:
            city_node = _find(node["children"], city)
        district_node = _find(city_node["children"], district) if city_node and district else None
        if district_node is None and district:
            # Province-administered counties (e.g. 济源市) or a mislabelled city.
            for candidate in node["children"]:
                found = _find(candidate["children"], district)
                if found:
                    city_node, district_node = candidate, found
                    break
        if city_node is None and city:
            for candidate in node["children"]:
                found = _find(candidate["children"], city)
                if found:
                    city_node, district_node = candidate, found
                    break
        if city_node is None:
            return None
        city_name = city_node["name"]
        if city_name.endswith("直辖县级行政区划") and district_node:
            city_name = district_node["name"]
        district_name = district_node["name"] if district_node else clean_text(district, 80)
        if not district_name:
            return None
        return {
            "province": node["name"], "province_code": node["code"],
            "city": city_name, "city_code": city_node["code"],
            "district": district_name,
            "district_code": district_node["code"] if district_node else "",
        }


    def name_prefix(self, province: str, school_name: str) -> tuple[str, str] | None:
        """(city, district) named at the start of a school name, e.g. ``东城区特殊教育学校``."""
        node = self.provinces.get(province) or self.provinces.get(_short_province(province))
        if node is None:
            return None
        name = school_name
        for prefix in (node["name"], _short_province(node["name"])):
            if name.startswith(prefix) and len(name) > len(prefix) + 2:
                name = name[len(prefix):]
                break
        best: tuple[int, str, str] | None = None
        for city in node["children"]:
            for label in {city["name"], _strip_suffix(city["name"])}:
                if len(label) >= 2 and name.startswith(label) and (best is None or len(label) > best[0]):
                    rest = name[len(label):]
                    district = next((d["name"] for d in city["children"]
                                     for dl in {d["name"], _strip_suffix(d["name"])}
                                     if len(dl) >= 2 and rest.startswith(dl)), "")
                    best = (len(label), city["name"], district)
            for district in city["children"]:
                for label in {district["name"], _strip_suffix(district["name"])}:
                    if len(label) >= 2 and name.startswith(label) and (best is None or len(label) > best[0]):
                        best = (len(label), city["name"], district["name"])
        return (best[1], best[2]) if best else None


def _strip_suffix(name: str) -> str:
    return re.sub(r"(市|区|县|自治县|自治州|地区|盟|旗)$", "", name)


def _short_province(name: str) -> str:
    return re.sub(r"(省|市|壮族自治区|回族自治区|维吾尔自治区|自治区|特别行政区)$", "", name)


def _find(nodes: Iterable[dict[str, Any]], name: str) -> dict[str, Any] | None:
    if not name:
        return None
    nodes = list(nodes)
    for node in nodes:
        if node["name"] == name:
            return node
    short = re.sub(r"(市|区|县|自治县|自治州|地区|盟|旗)$", "", name)
    if len(short) < 2:
        return None
    for node in nodes:
        if re.sub(r"(市|区|县|自治县|自治州|地区|盟|旗)$", "", node["name"]) == short:
            return node
    return None


def build_regions(pca_code: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize the statistical division tree (modood ``pca-code.json`` layout)."""
    tree = []
    for province in pca_code:
        code, name = str(province["code"]), clean_text(province["name"], 40)
        cities = []
        if code in MUNICIPALITIES:
            districts = [{"code": str(d["code"]), "name": clean_text(d["name"], 80)}
                         for c in province.get("children", []) for d in c.get("children", [])]
            cities.append({"code": code + "01", "name": name, "children": districts})
        else:
            for city in province.get("children", []):
                cities.append({"code": str(city["code"]), "name": clean_text(city["name"], 80),
                               "children": [{"code": str(d["code"]), "name": clean_text(d["name"], 80)}
                                            for d in city.get("children", [])]})
        tree.append({"code": code, "name": name, "children": cities})
    return tree


# --------------------------------------------------------------------------- sources

@dataclass
class Source:
    source_id: str
    title: str
    url: str
    license: str
    retrieved_on: str
    note: str = ""

    def as_dict(self) -> dict[str, str]:
        return {"source_id": self.source_id, "title": self.title, "url": self.url,
                "license": self.license, "retrieved_on": self.retrieved_on, "note": self.note}


def _entry(regions: RegionIndex, source: Source, name: str, province: str, city: str, district: str,
           *, school_type: str | None = None, address: str = "", region_basis: str = "source") -> dict[str, Any] | None:
    name = clean_text(name, 200)
    stype = school_type if school_type in SCHOOL_TYPES else classify_school(name)
    if not stype:
        return None
    resolved = regions.resolve(clean_text(province, 40), clean_text(city, 80), clean_text(district, 80))
    if resolved is None:
        return None
    region_code = resolved["district_code"] or resolved["city_code"]
    return {
        "school_code": school_code_for(region_code, resolved["province"], resolved["city"], resolved["district"], name),
        "school_name": name, **resolved, "school_type": stype,
        "address": clean_text(address, 300) or None,
        "initials": name_initials(name),
        "source_id": source.source_id, "updated_on": source.retrieved_on,
        "region_basis": region_basis,
    }


def parse_baidu(rows: list[dict[str, Any]], regions: RegionIndex, source: Source) -> list[dict[str, Any]]:
    """``[{name, province, city, area, address, location:{lat,lng}}]`` POI exports."""
    out = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        entry = _entry(regions, source, row.get("name", ""), row.get("province", ""), row.get("city", ""),
                       row.get("area", ""), address=row.get("address", ""))
        if entry:
            out.append(entry)
    return out


def _reference_points(rows: list[dict[str, Any]]) -> list[tuple[float, float, str, str, str]]:
    points = []
    for row in rows:
        loc = row.get("location") if isinstance(row, dict) else None
        if isinstance(loc, dict) and isinstance(loc.get("lat"), (int, float)) and isinstance(loc.get("lng"), (int, float)) and row.get("area"):
            points.append((float(loc["lat"]), float(loc["lng"]), row.get("province", ""), row.get("city", ""), row["area"]))
    return points


def _bd09_to_wgs84(lat: float, lng: float) -> tuple[float, float]:
    """Approximate BD-09 -> WGS-84 (error < 10 m); enough for district lookup."""
    x, y = lng - 0.0065, lat - 0.006
    z = math.sqrt(x * x + y * y) - 0.00002 * math.sin(y * math.pi * 3000 / 180)
    theta = math.atan2(y, x) - 0.000003 * math.cos(x * math.pi * 3000 / 180)
    gcj_lng, gcj_lat = z * math.cos(theta), z * math.sin(theta)
    dlat = _tlat(gcj_lng - 105, gcj_lat - 35)
    dlng = _tlng(gcj_lng - 105, gcj_lat - 35)
    rad = gcj_lat / 180 * math.pi
    magic = 1 - 0.006693421622965943 * math.sin(rad) ** 2
    sq = math.sqrt(magic)
    dlat = (dlat * 180) / ((6378245.0 * (1 - 0.006693421622965943)) / (magic * sq) * math.pi)
    dlng = (dlng * 180) / (6378245.0 / sq * math.cos(rad) * math.pi)
    return gcj_lat - dlat, gcj_lng - dlng


def _tlat(x: float, y: float) -> float:
    r = -100 + 2 * x + 3 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * math.sqrt(abs(x))
    r += (20 * math.sin(6 * x * math.pi) + 20 * math.sin(2 * x * math.pi)) * 2 / 3
    r += (20 * math.sin(y * math.pi) + 40 * math.sin(y / 3 * math.pi)) * 2 / 3
    r += (160 * math.sin(y / 12 * math.pi) + 320 * math.sin(y * math.pi / 30)) * 2 / 3
    return r


def _tlng(x: float, y: float) -> float:
    r = 300 + x + 2 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * math.sqrt(abs(x))
    r += (20 * math.sin(6 * x * math.pi) + 20 * math.sin(2 * x * math.pi)) * 2 / 3
    r += (20 * math.sin(x * math.pi) + 40 * math.sin(x / 3 * math.pi)) * 2 / 3
    r += (150 * math.sin(x / 12 * math.pi) + 300 * math.sin(x / 30 * math.pi)) * 2 / 3
    return r


def parse_osm(payload: dict[str, Any], regions: RegionIndex, source: Source,
              reference: list[dict[str, Any]], max_km: float = 25.0) -> list[dict[str, Any]]:
    """Overpass JSON; region from addr:* tags, else the nearest reference POI's district."""
    points = [(*_bd09_to_wgs84(lat, lng), p, c, a) for lat, lng, p, c, a in _reference_points(reference)]
    grid: dict[tuple[int, int], list[tuple[float, float, str, str, str]]] = {}
    for point in points:
        grid.setdefault((int(point[0] * 5), int(point[1] * 5)), []).append(point)
    out = []
    for element in payload.get("elements", []):
        tags = element.get("tags") or {}
        name = clean_text(tags.get("name:zh") or tags.get("name") or "", 200)
        if "学校" not in name and not name.endswith("学院"):
            continue
        if tags.get("amenity") not in {None, "school", "college"}:
            continue
        lat = element.get("lat", (element.get("center") or {}).get("lat"))
        lng = element.get("lon", (element.get("center") or {}).get("lon"))
        province, city, district, basis = tags.get("addr:province", ""), tags.get("addr:city", ""), tags.get("addr:district", ""), "source"
        if not (province and district) and isinstance(lat, (int, float)) and isinstance(lng, (int, float)):
            best, best_km = None, max_km
            gx, gy = int(lat * 5), int(lng * 5)
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for plat, plng, p, c, a in grid.get((gx + dx, gy + dy), []):
                        km = _haversine(lat, lng, plat, plng)
                        if km < best_km:
                            best, best_km = (p, c, a), km
            if best is None:
                # Remote schools without a nearby reference POI: accept only an
                # unambiguous full region name at the start of the school name.
                matches = {(p["name"], *named) for p in regions.tree
                           if (named := regions.name_prefix(p["name"], name)) and named[1]
                           and name.startswith(named[1]) and len(named[1]) >= 3}
                if len(matches) != 1:
                    continue
                province, city, district = next(iter(matches))
                entry = _entry(regions, source, name, province, city, district, region_basis="name_prefix")
                if entry:
                    out.append(entry)
                continue
            province, city, district, basis = *best, "nearest_poi"
            named = regions.name_prefix(province, name)
            if named and named[1]:
                city, district, basis = named[0], named[1], "name_prefix"
            elif named:
                nearest = regions.resolve(province, city, district)
                if nearest is None or nearest["city"] != named[0]:
                    continue
        entry = _entry(regions, source, name, province, city, district, region_basis=basis)
        if entry:
            out.append(entry)
    return out


def _haversine(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lng2 - lng1) / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(min(1.0, a)))


CSV_COLUMNS = {"学校名称": "name", "名称": "name", "省": "province", "省份": "province", "市": "city",
               "城市": "city", "区县": "district", "区/县": "district", "类型": "school_type", "学段": "school_type",
               "地址": "address", "name": "name", "province": "province", "city": "city",
               "district": "district", "school_type": "school_type", "address": "address"}


def parse_csv(path: Path, regions: RegionIndex, source: Source) -> list[dict[str, Any]]:
    """Official lists transcribed to CSV: 学校名称,省,市,区县[,类型][,地址] (UTF-8 with/without BOM)."""
    out = []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for raw in csv.DictReader(handle):
            row = {CSV_COLUMNS[k.strip()]: v for k, v in raw.items() if k and k.strip() in CSV_COLUMNS}
            entry = _entry(regions, source, row.get("name", ""), row.get("province", ""), row.get("city", ""),
                           row.get("district", ""), school_type=clean_text(row.get("school_type", ""), 20) or None,
                           address=row.get("address", ""))
            if entry:
                out.append(entry)
    return out


# --------------------------------------------------------------------------- storage

def _read_gz(path: Path) -> Any:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return json.load(handle)


def _write_gz(path: Path, payload: Any) -> None:
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    tmp = path.with_suffix(path.suffix + ".tmp")
    # mtime=0 keeps the archive byte-identical for identical content.
    with open(tmp, "wb") as handle, gzip.GzipFile(fileobj=handle, mode="wb", mtime=0, compresslevel=9) as gz:
        gz.write(raw)
    tmp.replace(path)


def load_regions(data_dir: Path = DATA_DIR) -> list[dict[str, Any]]:
    return _read_gz(data_dir / "regions.json.gz")


def write_regions(tree: list[dict[str, Any]], data_dir: Path = DATA_DIR) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    _write_gz(data_dir / "regions.json.gz", tree)


def merge_entries(entries: list[dict[str, Any]], source: Source, data_dir: Path = DATA_DIR,
                  *, dry_run: bool = False) -> dict[str, Any]:
    """Upsert by school_code (and de-duplicate same name within a district)."""
    started = time.monotonic()
    tree = load_regions(data_dir)
    names = {p["code"]: p["name"] for p in tree}
    by_province: dict[str, list[dict[str, Any]]] = {}
    for entry in entries:
        by_province.setdefault(entry["province_code"], []).append(entry)
    stats = {"received": len(entries), "inserted": 0, "updated": 0, "duplicates": 0, "provinces": 0}
    for code in sorted(set(names) | set(by_province)):
        path = data_dir / f"{code}.json.gz"
        existing = _read_gz(path)["entries"] if path.exists() else []
        index = {row["school_code"]: row for row in existing}
        seen_names = {(row["district"], row["school_name"]): row["school_code"] for row in existing}
        for entry in by_province.get(code, []):
            key = (entry["district"], entry["school_name"])
            if entry["school_code"] in index:
                if index[entry["school_code"]] != entry:
                    stats["updated"] += 1
                index[entry["school_code"]] = entry
            elif key in seen_names:
                stats["duplicates"] += 1
            else:
                index[entry["school_code"]] = entry
                seen_names[key] = entry["school_code"]
                stats["inserted"] += 1
        rows = sorted(index.values(), key=lambda r: (r["city_code"], r["district_code"], r["school_type"], r["school_name"]))
        if not dry_run and (rows or path.exists()):
            _write_gz(path, {"province_code": code, "province": names.get(code, ""), "entries": rows})
        stats["provinces"] += 1 if rows else 0
    if not dry_run:
        write_manifest(source, data_dir)
    stats["duration_ms"] = int((time.monotonic() - started) * 1000)
    return stats


def write_manifest(source: Source | None, data_dir: Path = DATA_DIR) -> dict[str, Any]:
    manifest_path = data_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    sources = {item["source_id"]: item for item in manifest.get("sources", [])}
    if source is not None:
        sources[source.source_id] = source.as_dict()
    tree = load_regions(data_dir)
    per_province, per_type, total = {}, {}, 0
    for province in tree:
        path = data_dir / f"{province['code']}.json.gz"
        rows = _read_gz(path)["entries"] if path.exists() else []
        per_province[province["code"]] = len(rows)
        total += len(rows)
        for row in rows:
            per_type[row["school_type"]] = per_type.get(row["school_type"], 0) + 1
    manifest = {
        "schema": 1, "updated_on": date.today().isoformat(), "entry_count": total,
        "province_count": sum(1 for count in per_province.values() if count),
        "region_province_count": len(tree),
        "per_province": per_province, "per_type": dict(sorted(per_type.items())),
        "sources": sorted(sources.values(), key=lambda s: s["source_id"]),
        "coverage_note": manifest.get("coverage_note") or (
            "公开数据汇编，不是教育部官方完整名录；特殊教育学校收录不完整，查不到时请手动填写，由管理员审核后归入目录。"),
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return manifest
