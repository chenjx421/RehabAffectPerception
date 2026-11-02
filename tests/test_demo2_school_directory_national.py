"""National school directory: packaged data, search, selection, manual review and HTTP contract.

Only public directory data and synthetic accounts are used; no student data.
"""

from __future__ import annotations

import gzip
import http.client
import json
import threading
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import pytest

from rehab_affect import demo2_school_directory as directory
from rehab_affect import school_directory_import as builder
from rehab_affect.evaluation_report_contract import school_id_from_context
from rehab_affect.school_directory import SchoolSelectionError, normalize_school_selection, school_directory
from rehab_affect.student_record_store import Demo2StudentRecordStore, SchoolReviewConflict
from src.rehab_affect import scenario_lab_server as server_module
from src.rehab_affect.student_record_store import Demo2StudentRecordStore as ServerStore

QINGPU_FUDU_CONTEXT = {"city": "上海市", "district": "青浦区", "school_name": "青浦区辅读学校"}
# Derived before the national directory existed; must never change.
QINGPU_FUDU_SCHOOL_ID = "school-5d8c59fda2054fabe91d8467"


# --------------------------------------------------------------------------- data + search

def test_packaged_regions_cover_all_31_provincial_divisions_with_nested_cities_and_districts():
    provinces = directory.region_children("")
    assert len(provinces) == 31
    names = {row["name"] for row in provinces}
    assert {"北京市", "上海市", "广东省", "新疆维吾尔自治区", "西藏自治区", "青海省", "海南省"} <= names
    for province in provinces:
        cities = directory.region_children(province["code"])
        assert cities, province["name"]
        assert directory.region_children(cities[0]["code"])
    assert [row["name"] for row in directory.region_children("31")] == ["上海市"]
    assert "青浦区" in {row["name"] for row in directory.region_children("3101")}
    with pytest.raises(directory.DirectoryQueryError):
        directory.region_children("99")
    with pytest.raises(directory.DirectoryQueryError):
        directory.region_children("abc")


def test_every_province_has_directory_schools_and_manifest_lists_sources():
    manifest = json.loads((builder.DATA_DIR / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["region_province_count"] == 31
    assert all(manifest["per_province"][row["code"]] > 0 for row in directory.region_children(""))
    assert manifest["per_type"]["特殊教育学校"] >= 250
    assert {source["source_id"] for source in manifest["sources"]} >= {"poi-zsts119", "osm-special"}
    assert all(source["retrieved_on"] and source["title"] for source in manifest["sources"])
    coverage = directory.coverage()
    assert coverage["complete"] is False and coverage["entry_count"] > 20000
    assert "不完整" in coverage["label"]


def test_search_without_region_returns_special_schools_from_several_provinces_paged_by_20():
    first = directory.search("特殊教育学校")
    assert first["total"] > 100 and first["page_size"] == 20 and len(first["items"]) == 20
    assert first["total_pages"] == (first["total"] + 19) // 20
    provinces = {item["province"] for page in (1, 2, 3) for item in directory.search("特殊教育学校", page=page)["items"]}
    assert len(provinces) >= 3
    second = directory.search("特殊教育学校", page=2)
    assert not {i["directory_id"] for i in first["items"]} & {i["directory_id"] for i in second["items"]}
    for item in first["items"]:
        assert item["school_type"] in directory.SCHOOL_TYPES
        assert item["region_label"] and "_name" not in item and "school_id" not in item


def test_qingpu_search_keeps_original_entries_ids_and_school_id():
    result = directory.search("青浦")
    ids = [item["directory_id"] for item in result["items"]]
    assert ids[:5] == sorted(ids[:5]) or set(ids[:5]) == {row["directory_id"] for row in school_directory()["entries"]}
    fudu = next(item for item in result["items"] if item["directory_id"] == "sh-qp-fudu")
    assert {key: fudu[key] for key in QINGPU_FUDU_CONTEXT} == QINGPU_FUDU_CONTEXT
    for mode in ("directory", "national"):
        selected = normalize_school_selection({"selection_source": mode, "directory_id": "sh-qp-fudu"})
        assert selected["context"] == QINGPU_FUDU_CONTEXT
        assert school_id_from_context(selected["context"]) == QINGPU_FUDU_SCHOOL_ID
    # The curated list itself is unchanged.
    assert len(school_directory()["entries"]) == 5


def test_region_type_and_initials_filters():
    haidian = directory.search("", province="11", city="1101", district="110108", school_type="特殊教育学校")
    assert haidian["items"] and all(i["district"] == "海淀区" and i["school_type"] == "特殊教育学校" for i in haidian["items"])
    initials = directory.search("tsjy")
    assert initials["total"] > 0 and all("特殊教育" in i["school_name"] for i in initials["items"][:5])
    scoped = directory.search("", scope="public_source")
    assert {i["directory_id"] for i in scoped["items"]} == {row["directory_id"] for row in school_directory()["entries"]}
    for bad in ({"province": "1"}, {"city": "11x1"}, {"school_type": "大学"}, {"page": 0}, {"page": "x"},
                {"province": "11", "city": "3101"}, {"scope": "all"}):
        with pytest.raises(directory.DirectoryQueryError):
            directory.search("学校", **bad)
    with pytest.raises(directory.DirectoryQueryError):
        directory.search("x" * 51)


def test_national_and_manual_selection_normalization():
    beijing = directory.search("盲人学校", province="11", district="110108")["items"][0]
    selected = normalize_school_selection({"selection_source": "national", "directory_id": beijing["directory_id"]})
    assert selected["context"] == {"city": "北京市", "district": "海淀区", "school_name": beijing["school_name"]}
    details = selected["details"]
    assert details["selection_source"] == "national" and details["school_code"] == beijing["directory_id"]
    assert details["province"] == "北京市" and details["district_code"] == "110108"
    manual = normalize_school_selection({"selection_source": "manual", "province_code": "63", "city_code": "6301",
                                         "district_code": "630102", "school_name": " 西宁市城东区测试特教学校 "})
    assert manual["context"] == {"city": "西宁市", "district": "城东区", "school_name": "西宁市城东区测试特教学校"}
    assert manual["details"]["review_status"] == "pending" and manual["details"]["source_status"] == "pending"
    for bad in ({"province_code": "63", "city_code": "1101", "district_code": "110108"},
                {"province_code": "63", "city_code": "6301", "district_code": "999999"},
                {"school_name": "学校"}, {"school_name": "a\nb测试学校"}, {"extra": "x"}):
        payload = {"selection_source": "manual", "province_code": "63", "city_code": "6301",
                   "district_code": "630102", "school_name": "西宁市测试学校", **bad}
        with pytest.raises(SchoolSelectionError):
            normalize_school_selection(payload)
    with pytest.raises(SchoolSelectionError):
        normalize_school_selection({"selection_source": "national", "directory_id": "cn000000-missing"})


def test_importer_upserts_csv_without_dropping_existing_entries(tmp_path):
    data = tmp_path / "schools"
    builder.write_regions(builder.load_regions(), data)
    regions = builder.RegionIndex(builder.load_regions(data))
    source = builder.Source("test-official", "测试官方名单", "https://example.invalid", "test", "2026-10-31")
    csv_path = tmp_path / "list.csv"
    csv_path.write_text("学校名称,省,市,区县,类型\n测试县特殊教育学校,青海省,西宁市,城东区,特殊教育学校\n"
                        "测试第一小学,青海省,西宁市,城东区,\n无效行,火星省,某市,某区,小学\n", encoding="utf-8")
    entries = builder.parse_csv(csv_path, regions, source)
    assert [e["school_name"] for e in entries] == ["测试县特殊教育学校", "测试第一小学"]
    assert entries[1]["school_type"] == "小学" and entries[0]["district_code"] == "630102"
    stats = builder.merge_entries(entries, source, data)
    assert stats["inserted"] == 2
    again = builder.merge_entries(entries, source, data)
    assert again["inserted"] == 0 and again["updated"] == 0
    other = builder.Source("test-other", "另一来源", "", "", "2026-11-01")
    extra = builder.parse_csv(csv_path, regions, other)[:1]
    extra[0]["school_name"] = "测试县第二特殊教育学校"
    extra[0]["school_code"] = builder.school_code_for("630102", "青海省", "西宁市", "城东区", "测试县第二特殊教育学校")
    builder.merge_entries(extra, other, data)
    with gzip.open(data / "63.json.gz", "rt", encoding="utf-8") as handle:
        stored = json.load(handle)["entries"]
    assert len(stored) == 3
    manifest = json.loads((data / "manifest.json").read_text(encoding="utf-8"))
    assert {s["source_id"] for s in manifest["sources"]} == {"test-official", "test-other"}


def test_school_type_classifier():
    assert builder.classify_school("某某区培智学校") == "特殊教育学校"
    assert builder.classify_school("长宁区辅读学校") == "辅读学校"
    assert builder.classify_school("某某市第一中学") == "中学"
    assert builder.classify_school("某某区实验小学") == "小学"
    assert builder.classify_school("某某高级中学") == "高中"
    assert builder.classify_school("某某职业技术学校") == "职校"
    assert builder.classify_school("某某大学") is None
    assert builder.classify_school("某某幼儿园") is None
    assert builder.classify_school("南京特殊教育师范学院") is None


# --------------------------------------------------------------------------- store

@pytest.fixture
def store_env(tmp_path):
    store = Demo2StudentRecordStore(tmp_path / "db.sqlite3", tmp_path / "documents")
    account = store.authenticate_account("t1", "RehabDemo2-school_uploader_01")
    token = store.create_account_session(account["account_id"])["token"]
    admin = store.authenticate_account("admin", "RehabDemo2-company_admin")
    admin_token = store.create_account_session(admin["account_id"])["token"]
    return store, token, admin_token


def _manual(name="青海测试县特殊教育学校"):
    return {"selection_source": "manual", "province_code": "63", "city_code": "6301", "district_code": "630102",
            "school_name": name}


def test_manual_school_is_pending_reviewable_and_searchable_after_approval(store_env):
    store, token, admin_token = store_env
    empty = store.account_school_context(token)["context"]
    saved = store.save_account_school_context(token, {**_manual(), "expected_context": empty, "confirmed": True})
    assert saved["context"] == {"city": "西宁市", "district": "城东区", "school_name": "青海测试县特殊教育学校"}
    code = saved["details"]["school_code"]
    assert code.startswith("manual-") and saved["details"]["review_status"] == "pending"
    # Re-saving the same school reuses the pending row.
    again = store.save_account_school_context(token, {**_manual(), "expected_context": saved["context"], "confirmed": True})
    assert again["details"]["school_code"] == code
    listing = store.admin_school_reviews(admin_token)
    assert listing["counts"]["pending"] == 1 and listing["schools"][0]["submitted_by"] == "school_uploader_01"
    with pytest.raises(PermissionError):
        store.admin_school_reviews(token)
    with pytest.raises(ValueError):
        store.review_manual_school(admin_token, {"school_code": code, "decision": "approve", "expected_version": 1})
    with pytest.raises(ValueError):
        store.review_manual_school(admin_token, {"school_code": code, "decision": "reject", "expected_version": 1})
    assert directory.search("青海测试县", extra=store.approved_manual_schools())["total"] == 0
    reviewed = store.review_manual_school(admin_token, {"school_code": code, "decision": "approve",
                                                        "school_type": "特殊教育学校", "expected_version": 1})
    assert reviewed["status"] == "approved" and reviewed["version"] == 2
    with pytest.raises(SchoolReviewConflict):
        store.review_manual_school(admin_token, {"school_code": code, "decision": "reject",
                                                 "review_note": "重复", "expected_version": 1})
    found = directory.search("青海测试县", extra=store.approved_manual_schools())
    assert found["total"] == 1 and found["items"][0]["directory_id"] == code
    assert store.account_school_context(token)["details"]["review_status"] == "approved"
    # An approved manual school can be selected through the national source.
    selected = store.save_account_school_context(token, {"selection_source": "national", "directory_id": code,
                                                         "expected_context": saved["context"], "confirmed": True})
    assert selected["context"] == saved["context"] and selected["details"]["source_status"] == "approved_manual"


def test_rejection_keeps_context_and_shows_status(store_env):
    store, token, admin_token = store_env
    empty = store.account_school_context(token)["context"]
    saved = store.save_account_school_context(token, {**_manual("青海测试驳回学校"), "expected_context": empty, "confirmed": True})
    code = saved["details"]["school_code"]
    store.review_manual_school(admin_token, {"school_code": code, "decision": "reject", "review_note": "名称不完整",
                                             "expected_version": 1})
    current = store.account_school_context(token)
    assert current["context"] == saved["context"]
    assert current["details"]["review_status"] == "rejected" and current["details"]["review_note"] == "名称不完整"
    assert store.admin_school_reviews(admin_token, "rejected")["counts"]["rejected"] == 1


# --------------------------------------------------------------------------- HTTP

def _request(port: int, method: str, path: str, payload: dict[str, Any] | None = None, *, cookie: str = ""):
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Content-Type": "application/json"}
    if cookie:
        headers["Cookie"] = cookie
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        raw = response.read()
        response_headers = {key.lower(): value for key, value in response.getheaders()}
        parsed = json.loads(raw.decode("utf-8")) if "application/json" in response_headers.get("content-type", "") else raw.decode("utf-8")
        return response.status, response_headers, parsed
    finally:
        connection.close()


def _login(port: int, username: str, password: str) -> str:
    status, headers, _ = _request(port, "POST", "/api/v1/demo2/auth/login", {"username": username, "password": password})
    assert status == 200
    return headers["set-cookie"].split(";", 1)[0]


@pytest.fixture()
def school_server(monkeypatch, tmp_path):
    monkeypatch.setenv("REHAB_DEMO2_ACCOUNT_PASSWORD_PREFIX", "school-dir-")
    monkeypatch.setenv("REHAB_DEMO2_SCHOOL_DEBUG_LOG_DIR", str(tmp_path / "logs"))
    for limiter in server_module._SCHOOL_LIMITERS.values():
        limiter._hits.clear()
    store = ServerStore(tmp_path / "school.sqlite3", tmp_path / "documents")
    monkeypatch.setattr(server_module, "get_demo2_student_store", lambda: store)
    monkeypatch.setattr(server_module, "load_seewo_demo2", lambda force=False: {"students": []})
    handler = server_module.create_handler(scenario_dir=tmp_path, model_path=tmp_path / "unused.json", policy_name="rule")
    httpd = server_module.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield httpd.server_port, store, tmp_path / "logs"
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=3)
        for limiter in server_module._SCHOOL_LIMITERS.values():
            limiter._hits.clear()


def _log_lines(folder: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for path in sorted(folder.glob("school_debug_*.jsonl"))
            for line in path.read_text(encoding="utf-8").splitlines()]


def test_http_search_requires_login_and_rate_limits_at_60_per_minute(school_server):
    port, _, logs = school_server
    for path in ("/api/v1/demo2/schools/search?q=特殊", "/api/v1/demo2/schools/regions"):
        status, _, body = _request(port, "GET", path.replace("特殊", "%E7%89%B9%E6%AE%8A"))
        assert status == 401 and body["error"]["code"] == "authentication_required"
    cookie = _login(port, "t1", "school-dir-school_uploader_01")
    status, _, body = _request(port, "GET", "/api/v1/demo2/schools/regions", cookie=cookie)
    assert status == 200 and len(body["regions"]) == 31
    query = urlencode({"q": "特殊教育学校"})
    status, _, body = _request(port, "GET", "/api/v1/demo2/schools/search?" + query, cookie=cookie)
    assert status == 200 and body["total"] > 100 and len(body["items"]) == 20
    status, _, body = _request(port, "GET", "/api/v1/demo2/schools/search?province=1", cookie=cookie)
    assert status == 400 and body["error"]["code"] == "invalid_region"
    for _ in range(58):
        status, _, _ = _request(port, "GET", "/api/v1/demo2/schools/search?" + urlencode({"q": "青浦"}), cookie=cookie)
        assert status == 200
    status, headers, body = _request(port, "GET", "/api/v1/demo2/schools/search?" + query, cookie=cookie)
    assert status == 429 and body["error"]["code"] == "school_search_rate_limited"
    assert int(headers["retry-after"]) >= 1
    # Another account has its own budget.
    other = _login(port, "t2", "school-dir-school_uploader_02")
    assert _request(port, "GET", "/api/v1/demo2/schools/search?" + query, cookie=other)[0] == 200
    lines = _log_lines(logs)
    searches = [line for line in lines if line["operation"] == "school_search"]
    assert {"ok", "invalid", "rate_limited"} <= {line["result"] for line in searches}
    ok = next(line for line in searches if line["result"] == "ok")
    assert {"ts", "result_count", "total", "duration_ms", "query_length", "page"} <= set(ok)
    raw = "\n".join(path.read_text(encoding="utf-8") for path in logs.glob("*.jsonl"))
    assert "特殊教育" not in raw and "青浦" not in raw


def test_http_select_outside_school_and_manual_review_flow(school_server):
    port, store, logs = school_server
    teacher = _login(port, "t1", "school-dir-school_uploader_01")
    hit = _request(port, "GET", "/api/v1/demo2/schools/search?" + urlencode(
        {"q": "盲人学校", "province": "11", "district": "110108"}), cookie=teacher)[2]["items"][0]
    empty = {"city": "", "district": "", "school_name": ""}
    status, _, body = _request(port, "POST", "/api/v1/demo2/school/context", {
        "selection_source": "national", "directory_id": hit["directory_id"], "expected_context": empty, "confirmed": True,
    }, cookie=teacher)
    assert status == 200 and body["context"] == {"city": "北京市", "district": "海淀区", "school_name": hit["school_name"]}
    status, _, task = _request(port, "POST", "/api/v1/demo2/upload/tasks", {
        "channel_id": "channel_1", "course_id": "dir-course", "course_name": "目录测试课程",
        "uploader_name": "测试", "session_id": "dir-session", "filename": "test.mp4",
        "byte_size": 1, "total_chunks": 1, "security_confirmed": True,
    }, cookie=teacher)
    assert status == 200 and task["task"]["school_context"]["school_name"] == hit["school_name"]
    status, _, home = _request(port, "GET", "/api/v1/demo2/home/summary", cookie=teacher)
    assert status == 200 and home["home"]["school"]["school_name"] == hit["school_name"]
    # Switch to a manual school: the task keeps its upload-time snapshot.
    status, _, body = _request(port, "POST", "/api/v1/demo2/school/context", {
        **_manual("青海手动测试学校"), "expected_context": body["context"], "confirmed": True}, cookie=teacher)
    assert status == 200 and body["details"]["review_status"] == "pending"
    code = body["details"]["school_code"]
    status, _, refreshed = _request(port, "GET", "/api/v1/demo2/upload/task?id=" + task["task"]["task_id"], cookie=teacher)
    assert status == 200 and refreshed["task"]["school_context"]["school_name"] == hit["school_name"]
    # Teachers cannot review; admins can.
    assert _request(port, "GET", "/api/v1/demo2/admin/schools", cookie=teacher)[0] == 403
    assert _request(port, "POST", "/api/v1/demo2/admin/schools/review", {
        "school_code": code, "decision": "approve", "school_type": "小学", "expected_version": 1}, cookie=teacher)[0] == 403
    admin = _login(port, "admin", "school-dir-company_admin")
    status, _, page = _request(port, "GET", "/demo2/admin/schools", cookie=admin)
    assert status == 200 and "学校目录审核" in page
    status, _, listing = _request(port, "GET", "/api/v1/demo2/admin/schools?status=pending", cookie=admin)
    assert status == 200 and [row["school_code"] for row in listing["schools"]] == [code]
    status, _, body = _request(port, "POST", "/api/v1/demo2/admin/schools/review", {
        "school_code": code, "decision": "approve", "school_type": "小学", "expected_version": 1}, cookie=admin)
    assert status == 200 and body["school"]["status"] == "approved"
    status, _, body = _request(port, "POST", "/api/v1/demo2/admin/schools/review", {
        "school_code": code, "decision": "reject", "review_note": "x", "expected_version": 1}, cookie=admin)
    assert status == 409 and body["error"]["code"] == "school_review_conflict"
    found = _request(port, "GET", "/api/v1/demo2/schools/search?" + urlencode({"q": "青海手动测试"}), cookie=teacher)[2]
    assert [item["directory_id"] for item in found["items"]] == [code]
    operations = {line["operation"] for line in _log_lines(logs)}
    assert {"school_search", "school_select", "school_manual_submit", "school_review", "school_review_list"} <= operations
    raw = "\n".join(path.read_text(encoding="utf-8") for path in logs.glob("*.jsonl"))
    assert "青海手动测试学校" not in raw and "盲人学校" not in raw


def test_both_school_renderers_are_identical():
    from rehab_affect.demo2_entry import render_school
    from rehab_affect.school_selection_page import render_school_selection_html
    account = {"role": "school_uploader", "username": "t1"}
    assert render_school(account) == render_school_selection_html(account)
    html = render_school(account)
    for element_id in ("regionProvince", "regionCity", "regionDistrict", "schoolSearch", "schoolResults",
                       "resultPrev", "resultNext", "toManual", "province", "city", "district", "schoolName"):
        assert f'id="{element_id}"' in html
    assert '<option value="national" selected>全国学校目录</option>' in html and "公开来源目录" in html
    assert "setTimeout(()=>runSearch(1),300)" in html


def test_search_errors_clear_stale_results_and_overlong_query_skips_request():
    from rehab_affect.demo2_ui_kit import UI_KIT_JS
    from rehab_affect.school_selection_page import render_school_selection_html
    html = render_school_selection_html({"role": "school_uploader", "username": "t1"})
    # A failed search must not leave the previous query's schools under the error text.
    assert "clearResultList('搜索失败：'+error.message)" in html
    assert "if(keyword.length>50){" in html and "请缩短后再搜索" in html
    # 429 keeps the results already on screen and only shows the wait time.
    assert "if(error.status===429){byId('resultInfo').textContent='搜索过于频繁" in html
    # The page explains 400/429 inline, so the global error notice stays quiet.
    assert "'/api/v1/demo2/schools/search':[400,429]" in UI_KIT_JS


def test_directory_warm_up_loads_in_background_and_can_be_disabled(monkeypatch):
    monkeypatch.setenv("REHAB_DEMO2_SCHOOL_DIRECTORY_WARMUP", "0")
    assert directory.warm_up_in_background() is None
    monkeypatch.delenv("REHAB_DEMO2_SCHOOL_DIRECTORY_WARMUP")
    monkeypatch.setattr(directory, "_DATASET", None)
    thread = directory.warm_up_in_background()
    assert thread is not None and thread.daemon and thread.name == "school-directory-warmup"
    thread.join(timeout=120)
    assert directory._DATASET is not None and len(directory._DATASET.entries) > 20000
    # Already loaded: nothing more to do.
    assert directory.warm_up_in_background() is None
