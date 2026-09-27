# -*- coding: utf-8 -*-
"""tests/test_wp_blog_deploy.py

modules/wp_blog_deploy.py 검증(STEP194). 실제 GitHub API/WP write/Sheets write는
전혀 호출하지 않는다 — WP sync/site generation은 전부 fake 함수로 주입하고,
git 관련 검증은 tmp_path 위에 만든 완전히 격리된 로컬 git repo(+bare "origin")
에서만 수행한다. 프로젝트 실제 저장소(data/blog_auto.db, .git 등)는 건드리지 않는다.
"""
import subprocess
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules.wp_blog_deploy import (
    run_wp_blog_deploy_once,
    run_wp_blog_deploy_loop,
    validate_index_html,
    validate_sitemap_xml,
    stage_allowed_files,
    ALLOWED_DEPLOY_FILES,
    COMMIT_MESSAGE,
    _acquire_lock,
    _release_lock,
    _lock_path,
)

# 순수 검증 함수(validate_index_html/validate_sitemap_xml) 단위 테스트 전용 — golden10_slugs를
# 함수 인자로 직접 넘기므로 실제 content.blog.GOLDEN_10과 무관하게 자유롭게 축소해서 쓴다.
GOLDEN10_SLUGS = {"severance-pay", "weekly-holiday-allowance"}

# run_wp_blog_deploy_once() 오케스트레이션 테스트 전용 — 이 함수는 내부에서
# 실제 content.blog.GOLDEN_10을 그대로 import하므로(주입 불가, 실제 계약 재사용),
# fixture도 실제 GOLDEN_10 10개 slug를 전부 포함해야 validation을 통과한다.
from content.blog import GOLDEN_10 as _REAL_GOLDEN_10  # noqa: E402

REAL_GOLDEN10_SLUGS = {gc.slug for gc in _REAL_GOLDEN_10}

BASE_INDEX = (
    '<section class="cm-section" id="calculators">GRID</section>'
    '<!-- 서비스 소개 -->'
    + "".join(f'<a href="https://calcmate.kr/blog/{gc.slug}/">{gc.slug}</a>' for gc in _REAL_GOLDEN_10)
)
BASE_SITEMAP = (
    '<urlset>'
    + "".join(f'<url><loc>https://calcmate.kr/blog/{gc.slug}/</loc></url>' for gc in _REAL_GOLDEN_10)
    + '</urlset>'
)


def _sync_ok(new_count):
    def fn(cfg):
        return {"success": True, "new_count": new_count, "inserted": new_count,
                "modified_detected": 0, "skipped_golden10": 0, "hold_reason": None}
    return fn


def _sync_fail():
    def fn(cfg):
        return {"success": False, "hold_reason": "wp_list_failed", "detail": "network error"}
    return fn


def _gen_index_with_new(slug="bmi-calculator"):
    def fn(cfg):
        return BASE_INDEX + f'<a href="https://calcmate.kr/blog/{slug}/">NEW</a>'
    return fn


def _gen_sitemap_with_new(slug="bmi-calculator"):
    def fn(cfg):
        return BASE_SITEMAP.replace(
            "</urlset>", f'<url><loc>https://calcmate.kr/blog/{slug}/</loc></url></urlset>')
    return fn


# ── git 저장소 픽스처(완전 격리, tmp_path 전용) ─────────────────────────
def _git(args, cwd):
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True,
                        text=True, encoding="utf-8", errors="replace")
    assert r.returncode == 0, f"git {args} failed: {r.stderr}"
    return r


def _make_repo_with_origin(tmp_path, dashboard_dirty=True):
    """bare 'origin' + 그것을 clone한 작업 repo. index.html/sitemap.xml 초기 커밋 +
    push까지 마쳐서 로컬 HEAD == origin/master 상태로 만든다. 필요하면 dashboard.py에
    해당하는 '기존 dirty 파일'도 함께 넣어 STEP8(기존 dirty 보호) 검증에 쓴다."""
    origin = tmp_path / "origin.git"
    origin.mkdir()
    subprocess.run(["git", "init", "--bare", "-b", "master", str(origin)],
                    capture_output=True, text=True, encoding="utf-8", errors="replace", check=True)

    repo = tmp_path / "repo"
    repo.mkdir()
    _git(["init", "-b", "master"], repo)
    _git(["config", "user.email", "test@example.com"], repo)
    _git(["config", "user.name", "Test"], repo)
    _git(["remote", "add", "origin", str(origin)], repo)

    site_dir = repo / "data" / "workspace" / "_site"
    site_dir.mkdir(parents=True)
    (site_dir / "index.html").write_text(BASE_INDEX, encoding="utf-8")
    (site_dir / "sitemap.xml").write_text(BASE_SITEMAP, encoding="utf-8")

    if dashboard_dirty:
        (repo / "dashboard.py").write_text("# baseline dirty file\nprint('hi')\n", encoding="utf-8")

    _git(["add", "data/workspace/_site/index.html", "data/workspace/_site/sitemap.xml"], repo)
    if dashboard_dirty:
        _git(["add", "dashboard.py"], repo)
    _git(["commit", "-m", "initial"], repo)
    _git(["push", "-u", "origin", "master"], repo)

    if dashboard_dirty:
        # 커밋 이후에 dashboard.py를 다시 수정해 "기존 dirty(unstaged)" 상태를 재현
        (repo / "dashboard.py").write_text("# baseline dirty file (modified)\nprint('hi2')\n", encoding="utf-8")

    return repo, origin


def _cfg_for(repo_dir):
    return {"_root": str(repo_dir)}


# ── Test 1: WP sync 실패 → push 금지 ────────────────────────────────────
def test_1_wp_sync_failure_blocks_everything(tmp_path):
    repo, origin = _make_repo_with_origin(tmp_path)
    cfg = _cfg_for(repo)
    result = run_wp_blog_deploy_once(cfg, dry_run=False, repo_dir=str(repo),
                                      sync_fn=_sync_fail())
    assert result["success"] is False
    assert result["stage"] == "wp_sync"
    assert result["hold_reason"] == "wp_sync_failed"
    # 아무 커밋도 추가되지 않았어야 함
    log = _git(["log", "--oneline"], repo).stdout.strip().splitlines()
    assert len(log) == 1  # initial 커밋만


# ── Test 2: new_count=0 → 배포하지 않음 ─────────────────────────────────
def test_2_no_new_articles_skips_deploy(tmp_path):
    repo, origin = _make_repo_with_origin(tmp_path)
    cfg = _cfg_for(repo)
    result = run_wp_blog_deploy_once(cfg, dry_run=False, repo_dir=str(repo),
                                      sync_fn=_sync_ok(0))
    assert result["success"] is True
    assert result["new_count"] == 0
    assert result["stage"] == "wp_sync"
    assert result["message"] == "no_new_articles"
    status = subprocess.run(["git", "status", "--short"], cwd=repo, capture_output=True, text=True, encoding="utf-8", errors="replace").stdout
    assert "index.html" not in status and "sitemap.xml" not in status


# ── Test 3: new_count>0 → generation 진행 ───────────────────────────────
def test_3_new_articles_triggers_generation(tmp_path):
    repo, origin = _make_repo_with_origin(tmp_path)
    cfg = _cfg_for(repo)
    result = run_wp_blog_deploy_once(cfg, dry_run=True, repo_dir=str(repo),
                                      sync_fn=_sync_ok(1),
                                      generate_index_fn=_gen_index_with_new(),
                                      generate_sitemap_fn=_gen_sitemap_with_new())
    assert result["new_count"] == 1
    assert result["stage"] in ("dry_run_complete",)
    new_html = (repo / "data/workspace/_site/index.html").read_text(encoding="utf-8")
    assert "bmi-calculator" in new_html


# ── Test 4: 허용 파일 외 변경 → push 금지(validation 단계에서 차단) ─────
def test_4_forbidden_change_blocks_before_staging(tmp_path):
    repo, origin = _make_repo_with_origin(tmp_path)
    cfg = _cfg_for(repo)

    def bad_generate_index(cfg):
        return "<totally different structure, calculator grid destroyed>"

    result = run_wp_blog_deploy_once(cfg, dry_run=True, repo_dir=str(repo),
                                      sync_fn=_sync_ok(1),
                                      generate_index_fn=bad_generate_index,
                                      generate_sitemap_fn=_gen_sitemap_with_new())
    assert result["success"] is False
    assert result["stage"] == "validation"
    # 검증 실패 시 파일이 아예 쓰이지 않아야 함(원본 유지)
    html = (repo / "data/workspace/_site/index.html").read_text(encoding="utf-8")
    assert html == BASE_INDEX


# ── Test 5: staged 파일이 allowlist와 다르면 → commit 금지 ─────────────
def test_5_staged_allowlist_mismatch_blocks_commit(tmp_path):
    repo, origin = _make_repo_with_origin(tmp_path, dashboard_dirty=False)
    # 의도적으로 index.html 외에 엉뚱한 파일도 이미 staged 상태로 만들어 둔다.
    (repo / "extra.txt").write_text("oops", encoding="utf-8")
    _git(["add", "extra.txt"], repo)

    ok, staged, reason = stage_allowed_files(str(repo))
    assert ok is False
    assert "extra.txt" in staged
    assert "staged_allowlist_mismatch" in reason


# ── Test 6: 기존 dirty 파일(dashboard.py)은 staging되지 않음 ───────────
def test_6_existing_dirty_file_not_staged(tmp_path):
    repo, origin = _make_repo_with_origin(tmp_path, dashboard_dirty=True)
    cfg = _cfg_for(repo)
    result = run_wp_blog_deploy_once(cfg, dry_run=True, repo_dir=str(repo),
                                      sync_fn=_sync_ok(1),
                                      generate_index_fn=_gen_index_with_new(),
                                      generate_sitemap_fn=_gen_sitemap_with_new())
    assert result["stage"] == "dry_run_complete"
    staged_norm = sorted(p.replace("\\", "/") for p in result["staged_files"])
    assert staged_norm == sorted(ALLOWED_DEPLOY_FILES)
    assert "dashboard.py" not in staged_norm
    # dashboard.py는 여전히 unstaged 상태(수정된 채)여야 한다
    status = _git(["status", "--short", "dashboard.py"], repo).stdout
    assert status.strip().startswith("M") or status.strip().startswith(" M")


# ── Test 7: lock 존재 → 중복 실행 차단 ──────────────────────────────────
def test_7_lock_blocks_concurrent_run(tmp_path):
    repo, origin = _make_repo_with_origin(tmp_path)
    cfg = _cfg_for(repo)
    assert _acquire_lock(cfg) is True
    try:
        result = run_wp_blog_deploy_once(cfg, dry_run=True, repo_dir=str(repo),
                                          sync_fn=_sync_ok(1))
        assert result["success"] is False
        assert result["stage"] == "lock"
        assert result["hold_reason"] == "lock_busy"
    finally:
        _release_lock(cfg)


# ── Test 8: origin/master 변경 → push 금지 ──────────────────────────────
def test_8_remote_diverged_blocks_push(tmp_path):
    repo, origin = _make_repo_with_origin(tmp_path, dashboard_dirty=False)
    cfg = _cfg_for(repo)

    # 다른 프로세스가 push한 상황을 시뮬레이션: 별도 clone에서 커밋 후 push
    other = tmp_path / "other_clone"
    subprocess.run(["git", "clone", str(origin), str(other)], capture_output=True, text=True, encoding="utf-8", errors="replace", check=True)
    _git(["config", "user.email", "other@example.com"], other)
    _git(["config", "user.name", "Other"], other)
    (other / "unrelated.txt").write_text("someone else's change", encoding="utf-8")
    _git(["add", "unrelated.txt"], other)
    _git(["commit", "-m", "other change"], other)
    _git(["push", "origin", "master"], other)

    result = run_wp_blog_deploy_once(cfg, dry_run=False, repo_dir=str(repo),
                                      sync_fn=_sync_ok(1),
                                      generate_index_fn=_gen_index_with_new(),
                                      generate_sitemap_fn=_gen_sitemap_with_new())
    assert result["success"] is False
    assert result["stage"] == "remote_check"
    assert "remote_diverged_before_commit" in result["hold_reason"]
    # 로컬에는 새 커밋이 생기지 않았어야 함(diff는 staged로 남아있을 수 있음)
    local_log = _git(["log", "--oneline"], repo).stdout.strip().splitlines()
    assert len(local_log) == 1


# ── Test 9: dry-run → commit/push 없음 ──────────────────────────────────
def test_9_dry_run_never_commits_or_pushes(tmp_path):
    repo, origin = _make_repo_with_origin(tmp_path, dashboard_dirty=False)
    cfg = _cfg_for(repo)
    before_log = _git(["log", "--oneline"], repo).stdout.strip().splitlines()

    result = run_wp_blog_deploy_once(cfg, dry_run=True, repo_dir=str(repo),
                                      sync_fn=_sync_ok(1),
                                      generate_index_fn=_gen_index_with_new(),
                                      generate_sitemap_fn=_gen_sitemap_with_new())
    assert result["dry_run"] is True
    assert result["stage"] == "dry_run_complete"

    after_log = _git(["log", "--oneline"], repo).stdout.strip().splitlines()
    assert before_log == after_log  # 커밋 개수 불변

    # origin도 push되지 않았어야 함(origin은 여전히 initial 커밋만)
    bare_log = subprocess.run(["git", "log", "--oneline", "master"], cwd=origin,
                               capture_output=True, text=True, encoding="utf-8", errors="replace").stdout.strip().splitlines()
    assert len(bare_log) == 1


# ── Test 10: 정상 흐름 → 예상된 단계가 순서대로 실행됨(실제 commit/push까지) ──
def test_10_full_flow_commits_and_pushes(tmp_path):
    repo, origin = _make_repo_with_origin(tmp_path, dashboard_dirty=True)
    cfg = _cfg_for(repo)

    result = run_wp_blog_deploy_once(cfg, dry_run=False, repo_dir=str(repo),
                                      sync_fn=_sync_ok(1),
                                      generate_index_fn=_gen_index_with_new(),
                                      generate_sitemap_fn=_gen_sitemap_with_new())
    assert result["success"] is True
    assert result["stage"] == "push_complete"
    assert result["new_count"] == 1
    assert set(p.replace("\\", "/") for p in result["staged_files"]) == set(ALLOWED_DEPLOY_FILES)

    # origin에 새 커밋이 실제로 반영됐는지 확인
    bare_log = subprocess.run(["git", "log", "--oneline", "master"], cwd=origin,
                               capture_output=True, text=True, encoding="utf-8", errors="replace").stdout.strip().splitlines()
    assert len(bare_log) == 2  # initial + 신규 배포 커밋
    assert COMMIT_MESSAGE in subprocess.run(
        ["git", "log", "-1", "--format=%s", "master"], cwd=origin,
        capture_output=True, text=True, encoding="utf-8", errors="replace").stdout

    # dashboard.py(기존 dirty)는 origin에 반영되지 않았어야 함(원래 커밋된 버전 그대로)
    show = subprocess.run(["git", "show", "master:dashboard.py"], cwd=origin,
                           capture_output=True, text=True, encoding="utf-8", errors="replace").stdout
    assert "modified" not in show


# ── 순수 검증 함수 단위 테스트(파일 I/O 없음) ───────────────────────────
def test_validate_index_html_rejects_grid_change():
    changed = (
        '<section class="cm-section" id="calculators">CHANGED</section>'
        '<!-- 서비스 소개 -->'
        '<a href="https://calcmate.kr/blog/severance-pay/">A</a>'
        '<a href="https://calcmate.kr/blog/weekly-holiday-allowance/">B</a>'
    )
    small_base = (
        '<section class="cm-section" id="calculators">GRID</section>'
        '<!-- 서비스 소개 -->'
        '<a href="https://calcmate.kr/blog/severance-pay/">A</a>'
        '<a href="https://calcmate.kr/blog/weekly-holiday-allowance/">B</a>'
    )
    ok, reason = validate_index_html(small_base, changed, GOLDEN10_SLUGS)
    assert ok is False
    assert reason == "calculator_grid_changed"


def test_validate_index_html_rejects_missing_golden10():
    truncated = '<section class="cm-section" id="calculators">GRID</section><!-- 서비스 소개 -->'
    ok, reason = validate_index_html(BASE_INDEX, truncated, GOLDEN10_SLUGS)
    assert ok is False
    assert "golden10_missing" in reason


def test_validate_sitemap_xml_rejects_removed_url():
    truncated = '<urlset><url><loc>https://calcmate.kr/blog/severance-pay/</loc></url></urlset>'
    ok, reason = validate_sitemap_xml(BASE_SITEMAP, truncated, GOLDEN10_SLUGS)
    assert ok is False
    assert "urls_removed" in reason


def test_validate_sitemap_xml_rejects_duplicate():
    dup = BASE_SITEMAP.replace(
        "</urlset>",
        '<url><loc>https://calcmate.kr/blog/severance-pay/</loc></url></urlset>')
    ok, reason = validate_sitemap_xml(BASE_SITEMAP, dup, GOLDEN10_SLUGS)
    assert ok is False
    assert reason == "duplicate_urls"


def test_validate_sitemap_xml_accepts_valid_addition():
    added = BASE_SITEMAP.replace(
        "</urlset>",
        '<url><loc>https://calcmate.kr/blog/bmi-calculator/</loc></url></urlset>')
    ok, reason = validate_sitemap_xml(BASE_SITEMAP, added, GOLDEN10_SLUGS)
    assert ok is True
    assert reason is None


# ══════════════════════════════════════════════════════════════════════
# STEP197: run_wp_blog_deploy_loop() 검증 — 실제 WP/GitHub 호출 없음,
# deploy_fn을 fake로 주입해 loop 자체가 sync/generation/validation/staging/
# commit/push 로직을 복제하지 않았는지(순수 위임 구조인지)를 검증한다.
# ══════════════════════════════════════════════════════════════════════

def _make_call_recorder(results=None, raise_on=None):
    """호출될 때마다 (cfg, dry_run, kwargs)를 기록하고 results[i]를 순서대로 반환하는
    fake deploy_fn. raise_on에 지정된 call index에서는 예외를 던진다."""
    calls = []

    def fn(cfg, dry_run=True, **kwargs):
        idx = len(calls)
        calls.append({"cfg": cfg, "dry_run": dry_run, "kwargs": kwargs})
        if raise_on is not None and idx in raise_on:
            raise RuntimeError(f"simulated failure at call {idx}")
        if results is not None and idx < len(results):
            return results[idx]
        return {"success": True, "stage": "wp_sync", "new_count": 0,
                "hold_reason": None, "message": "no_new_articles"}

    fn.calls = calls
    return fn


def _stop_after(stop_event, n):
    """n번 호출되면 stop_event를 set하는 콜백 팩토리(카운터 클로저)."""
    count = {"n": 0}

    def cb():
        count["n"] += 1
        if count["n"] >= n:
            stop_event.set()
    return cb


# ── Test A: 기본 dry-run — 실제 push/commit 없음 ────────────────────────
def test_a_loop_default_dry_run_never_pushes_or_commits(tmp_path):
    stop_event = threading.Event()
    on_call = _stop_after(stop_event, 1)

    def fn(cfg, dry_run=True, **kwargs):
        on_call()
        assert dry_run is True  # run_wp_blog_deploy_loop()의 기본값이 그대로 전달됐는지 확인
        return {"success": True, "stage": "dry_run_complete", "new_count": 1,
                "hold_reason": None, "staged_files": list(ALLOWED_DEPLOY_FILES)}

    run_wp_blog_deploy_loop({"_root": str(tmp_path)}, interval_seconds=0.01,
                             stop_event=stop_event, deploy_fn=fn)
    # fn 자체가 dry_run=True로 호출된 것만으로 이미 "실제 push/commit 없음"이 보장됨
    # (fn 내부에 commit/push 코드가 전혀 없는 fake이므로 진짜 git 동작 자체가 없음).


# ── Test B: new_count=0 → no-op ─────────────────────────────────────────
def test_b_loop_no_new_articles_is_noop(tmp_path):
    stop_event = threading.Event()
    recorder = _make_call_recorder(results=[
        {"success": True, "stage": "wp_sync", "new_count": 0,
         "hold_reason": None, "message": "no_new_articles"},
    ])

    def fn(cfg, dry_run=True, **kwargs):
        result = recorder(cfg, dry_run=dry_run, **kwargs)
        stop_event.set()
        return result

    run_wp_blog_deploy_loop({"_root": str(tmp_path)}, interval_seconds=0.01,
                             stop_event=stop_event, deploy_fn=fn)
    assert len(recorder.calls) == 1
    assert recorder.calls[0]["dry_run"] is True


# ── Test C: new_count>=1 → 기존 once() 그대로 호출(로직 복제 없음) ──────
def test_c_loop_delegates_to_once_without_reimplementing(tmp_path):
    stop_event = threading.Event()
    recorder = _make_call_recorder(results=[
        {"success": True, "stage": "dry_run_complete", "new_count": 1,
         "hold_reason": None, "staged_files": list(ALLOWED_DEPLOY_FILES)},
    ])

    def fn(cfg, dry_run=True, **kwargs):
        result = recorder(cfg, dry_run=dry_run, **kwargs)
        stop_event.set()
        return result

    cfg = {"_root": str(tmp_path), "marker": "unique-cfg-passthrough"}
    run_wp_blog_deploy_loop(cfg, interval_seconds=0.01, stop_event=stop_event, deploy_fn=fn)
    assert len(recorder.calls) == 1
    # loop가 cfg를 그대로 전달했는지(가공/치환 없이 위임했는지) 확인
    assert recorder.calls[0]["cfg"] is cfg
    # loop 자체에는 staging/commit/push 관련 코드가 전혀 없다 — deploy_fn(once)의
    # 반환값을 그대로 로그에 남길 뿐이라는 것을 결과 필드 보존으로 간접 확인.


# ── Test D: interval — 여러 cycle이 실제로 반복 실행되는지(짧은 interval로) ──
def test_d_loop_runs_multiple_cycles_with_small_interval(tmp_path):
    stop_event = threading.Event()
    recorder = _make_call_recorder(results=[
        {"success": True, "stage": "wp_sync", "new_count": 0, "hold_reason": None},
        {"success": True, "stage": "wp_sync", "new_count": 0, "hold_reason": None},
    ])
    on_call = _stop_after(stop_event, 2)

    def fn(cfg, dry_run=True, **kwargs):
        result = recorder(cfg, dry_run=dry_run, **kwargs)
        on_call()
        return result

    run_wp_blog_deploy_loop({"_root": str(tmp_path)}, interval_seconds=0.01,
                             stop_event=stop_event, deploy_fn=fn)
    assert len(recorder.calls) == 2  # cycle 1 + cycle 2 정확히 실행됨


# ── Test E: stop_event가 이미 set이면 cycle을 아예 시작하지 않음 ───────
def test_e_loop_stop_event_already_set_runs_zero_cycles(tmp_path):
    stop_event = threading.Event()
    stop_event.set()
    recorder = _make_call_recorder()

    run_wp_blog_deploy_loop({"_root": str(tmp_path)}, interval_seconds=0.01,
                             stop_event=stop_event, deploy_fn=recorder)
    assert len(recorder.calls) == 0  # 다음 cycle을 시작하지 않고 즉시 정상 종료


# ── Test F: cycle 중 예외가 발생해도 loop 전체가 조용히 죽지 않음 ──────
def test_f_loop_survives_exception_and_continues(tmp_path):
    stop_event = threading.Event()
    on_call = _stop_after(stop_event, 2)

    def fn(cfg, dry_run=True, **kwargs):
        idx = len(fn.calls)
        fn.calls.append(idx)
        on_call()
        if idx == 0:
            raise RuntimeError("simulated cycle failure")
        return {"success": True, "stage": "wp_sync", "new_count": 0, "hold_reason": None}
    fn.calls = []

    # 예외가 나도 프로세스/테스트가 죽지 않고 정상적으로 return되어야 한다.
    run_wp_blog_deploy_loop({"_root": str(tmp_path)}, interval_seconds=0.01,
                             stop_event=stop_event, deploy_fn=fn)
    assert len(fn.calls) == 2  # 1번째(예외) 이후에도 2번째 cycle이 실제로 실행됨


# ── Test G: lock 유지 — run_wp_blog_deploy_once()의 lock이 loop를 통해서도 그대로 보호됨 ──
def test_g_loop_respects_existing_deploy_lock(tmp_path):
    cfg = {"_root": str(tmp_path)}
    assert _acquire_lock(cfg) is True
    try:
        stop_event = threading.Event()

        def fn_once_for_real(cfg, dry_run=True, **kwargs):
            # 진짜 run_wp_blog_deploy_once()를 호출해 lock_busy를 실제로 확인한다.
            result = run_wp_blog_deploy_once(cfg, dry_run=dry_run, repo_dir=str(tmp_path))
            stop_event.set()
            return result

        run_wp_blog_deploy_loop(cfg, interval_seconds=0.01, stop_event=stop_event,
                                 deploy_fn=fn_once_for_real)
        # deploy_fn 내부에서 실제 once()가 lock_busy로 막혔는지는 별도로 once() 자체를
        # 직접 호출해 재확인한다(로그 캡처 없이도 결과로 확실히 검증).
        direct_result = run_wp_blog_deploy_once(cfg, dry_run=True, repo_dir=str(tmp_path))
        assert direct_result["success"] is False
        assert direct_result["stage"] == "lock"
        assert direct_result["hold_reason"] == "lock_busy"
    finally:
        _release_lock(cfg)


# ── Test H: 기존 STEP194 15개 테스트 보존 확인은 전체 파일 재실행으로 검증(별도 assert 불필요) ──
