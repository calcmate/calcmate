# -*- coding: utf-8 -*-
"""tests/test_ci_summary_gate.py — CI Summary job의 fail-closed 계약 검증.

배경: .github/workflows/ci.yml의 summary job(CI Summary)은 needs 결과를 표로만
기록하고 종료 코드를 남기지 않아, 하위 job이 failure여도 CI Summary job 자체는
success로 끝났다(GitHub run 39214845180 등 실측). 이 파일은 실제 ci.yml을 읽어

  1) "Enforce required job results" step이 needs의 모든 job 결과를 env로 받는지,
  2) GitHub Actions의 needs.<job>.result 값(success/failure/cancelled/skipped)별로
     그 step 스크립트를 bash로 실제 실행했을 때 종료 코드가 계약대로인지

확인한다. 실제 GitHub Actions 실행·네트워크·운영 데이터 접근은 없다.
"""

import itertools
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

CI_YML = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "ci.yml"
STEP_NAME = "Enforce required job results"
NEEDS_EXPR = re.compile(r"^\$\{\{\s*needs\.([A-Za-z0-9_-]+)\.result\s*\}\}$")
RESULTS = ("success", "failure", "cancelled", "skipped")

BASH = shutil.which("bash")
pytestmark = pytest.mark.skipif(BASH is None, reason="bash not available")


def _summary_job() -> dict:
    workflow = yaml.safe_load(CI_YML.read_text(encoding="utf-8"))
    return workflow["jobs"]["summary"]


def _enforce_step() -> dict:
    steps = [s for s in _summary_job()["steps"] if s.get("name") == STEP_NAME]
    assert len(steps) == 1, f"'{STEP_NAME}' step must exist exactly once"
    return steps[0]


def _env_to_job() -> dict[str, str]:
    """step env 이름 → needs job id 매핑 (예: QUALITY_GATES_RESULT → quality-gates)."""
    mapping = {}
    for env_name, expr in _enforce_step()["env"].items():
        match = NEEDS_EXPR.match(str(expr).strip())
        assert match, f"env {env_name} must read needs.<job>.result, got {expr!r}"
        mapping[env_name] = match.group(1)
    return mapping


def _run_step(results_by_job: dict[str, str]) -> subprocess.CompletedProcess:
    env = {name: results_by_job[job] for name, job in _env_to_job().items()}
    return subprocess.run(
        [BASH, "-e", "-c", _enforce_step()["run"]],
        env=env, capture_output=True, text=True, timeout=30,
    )


def test_summary_runs_always_and_enforces_every_needed_job():
    job = _summary_job()
    assert job.get("if") == "always()"
    assert sorted(_env_to_job().values()) == sorted(job["needs"])


def test_all_required_success_passes():
    proc = _run_step({job: "success" for job in _summary_job()["needs"]})
    assert proc.returncode == 0, proc.stdout + proc.stderr


@pytest.mark.parametrize("bad_result", ["failure", "cancelled", "skipped", ""])
def test_any_required_non_success_fails(bad_result):
    needs = _summary_job()["needs"]
    for bad_job in needs:
        results = {job: "success" for job in needs}
        results[bad_job] = bad_result
        proc = _run_step(results)
        assert proc.returncode != 0, f"{bad_job}={bad_result!r} must fail CI Summary"
        assert f"Required job '{bad_job}'" in proc.stdout


def test_every_result_combination_fails_unless_all_success():
    needs = _summary_job()["needs"]
    for combo in itertools.product(RESULTS, repeat=len(needs)):
        proc = _run_step(dict(zip(needs, combo)))
        all_success = all(r == "success" for r in combo)
        assert (proc.returncode == 0) == all_success, dict(zip(needs, combo))
