"""Reproduce offline tests, build checks and diagnostic capability probes.

From repository root: python -m evaluation.run
No production traffic, no provider calls, no real session directory is used.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]


def run_stage(name, command, cwd, env, out, timeout=180):
    started = time.perf_counter()
    try:
        result = subprocess.run(command, cwd=cwd, env=env, capture_output=True,
                                text=True, encoding="utf-8", errors="replace", timeout=timeout)
        code, log = result.returncode, result.stdout + "\n" + result.stderr
    except subprocess.TimeoutExpired as exc:
        code, log = 124, f"Stage timed out after {timeout}s. Partial logs: {exc.stdout!r}\n{exc.stderr!r}"
    except OSError as exc:
        code, log = 127, f"{type(exc).__name__}: {exc}"
    (out / f"{name}.log").write_text(log.rstrip() + "\n", encoding="utf-8")
    return dict(name=name, command=command, exit_code=code,
                duration_seconds=round(time.perf_counter() - started, 3), log=f"{name}.log")


def source_hash():
    digest = hashlib.sha256()
    roots = [ROOT / p for p in ("backend/app", "backend/tests", "backend/system_tests", "frontend/src", "frontend/e2e", "frontend/public", "evaluation")]
    for directory in roots:
        for p in sorted(directory.rglob("*")):
            if p.suffix not in (".py", ".tsx", ".ts", ".css", ".json", ".csv") or any(x in p.parts for x in ("runs", "reports", "__pycache__")):
                continue
            digest.update(p.relative_to(ROOT).as_posix().encode())
            digest.update(p.read_bytes())
    for name in ("frontend/package.json", "frontend/package-lock.json", "frontend/playwright.config.ts"):
        digest.update(name.encode())
        digest.update((ROOT / name).read_bytes())
    return digest.hexdigest()


def junit_summary(path):
    if not path.exists():
        return {"error": "No JUnit file; tests may not have started or completed"}
    cases = list(ET.parse(path).getroot().iter("testcase"))
    result = dict(total=len(cases), passed=0, failed=0, errors=0, skipped=0, xfailed=0, known_defects=[])
    for case in cases:
        skipped = case.find("skipped")
        if case.find("failure") is not None:
            result["failed"] += 1
        elif case.find("error") is not None:
            result["errors"] += 1
        elif skipped is not None:
            if skipped.get("type") == "pytest.xfail":
                result["xfailed"] += 1
                result["known_defects"].append({"test": case.get("name"), "reason": skipped.get("message")})
            else:
                result["skipped"] += 1
        else:
            result["passed"] += 1
    return result


def percent(value):
    return f"{value:.1%}" if value is not None else "不适用（分母为0）"


def browser_summary(path):
    if not path.exists():
        return {"error": "Browser stage did not produce results"}
    raw = json.loads(path.read_text(encoding="utf-8"))
    cases = []
    def walk(suite):
        for spec in suite.get("specs", []):
            for test in spec.get("tests", []):
                results = test.get("results", [])
                last = results[-1] if results else {}
                cases.append({"title": spec["title"], "project": test.get("projectName"),
                    "status": last.get("status", "missing"), "duration_ms": last.get("duration"),
                    "annotations": test.get("annotations", []),
                    "errors": [e.get("message", "") for e in last.get("errors", [])]})
        for nested in suite.get("suites", []):
            walk(nested)
    for suite in raw.get("suites", []):
        walk(suite)
    return {"stats": raw.get("stats", {}), "cases": cases,
            "projects": [{"name": p.get("name"), "viewport": p.get("use", {}).get("viewport") or p.get("metadata", {}).get("viewport")}
                         for p in raw.get("config", {}).get("projects", [])]}


def markdown(result):
    tests, benchmark = result["tests"], result.get("benchmark")
    lines = ["# 研证离线系统测试与能力评测报告", "", f"执行时间：{result['started_at_utc']}（UTC）", "",
             f"源码基线：`{result['source_commit']}`；工作区包含本轮新增评测代码。",
             f"源码指纹：`{result['source_sha256']}`", "",
             "## 结论边界", "",
             "本次没有读取真实会话、访问线上服务或调用智谱。模型故障测试使用桩；合成案例的候选事实由脚本确认。生产冷启动、真实模型与学生效果未验证。浏览器交互以独立浏览器阶段记录为准。", "",
             "## 测试与构建", "",
             f"测试 {tests.get('total', 0)} 项：通过 {tests.get('passed', 0)}，失败 {tests.get('failed', 0)}，错误 {tests.get('errors', 0)}，已复现未修缺陷 XFAIL {tests.get('xfailed', 0)}，其他跳过 {tests.get('skipped', 0)}。XFAIL 不计为通过。", "",
             "| 阶段 | 退出码 | 秒 | 日志 |", "| --- | ---: | ---: | --- |"]
    for stage in result["stages"]:
        lines.append(f"| {stage['name']} | {stage['exit_code']} | {stage['duration_seconds']} | [{stage['log']}]({stage['log']}) |")
    lines += ["", "## 已复现的未修缺陷", ""]
    lines.extend(f"- {x['reason']}。复现：`{x['test']}`。" for x in tests.get("known_defects", []))
    if not tests.get("known_defects"):
        lines.append("本次没有预期失败标记；原5项缺陷已转为必须正常通过的回归测试。")
    lines += ["", f"本地回归发布门槛：**{'通过' if result['release_gate']['passed'] else '未通过'}**。该门槛不证明真实模型或教学效果。",
              "`known-defects-audit` 独立执行原5项缺陷用例；退出码0表示这些回归通过，退出码1仍代表真实失败。"]
    if result.get("browser"):
        b = result["browser"]
        lines += ["", "## 真实浏览器回归", "", f"浏览器统计：{json.dumps(b.get('stats', {}), ensure_ascii=False)}。", "",
                  "| 项目 | 测试 | 结果 |", "| --- | --- | --- |"]
        lines.extend(f"| {c['project']} | {c['title']} | {c['status']} |" for c in b.get("cases", []))
        lines += ["", "浏览器仅访问隔离本机服务，使用临时浏览器上下文，不使用用户Chrome资料。覆盖上传与失败保留、事实确认、追问、复查、练习保存、刷新、非法本地状态恢复和390/768/1440宽度；不替代真实供应商或生产部署验收。"]
    if benchmark:
        s = benchmark["summary"]
        lines += ["", "## 合成能力探针", "",
                  "这些案例是公开开发诊断集，标签由开发者预先设定，未经教师独立标注。下面数字仅描述本轮规则流程，不能作为真实科研准确率或获奖依据。", "",
                  f"案例数 {s['n_cases']}；数据集指纹 `{benchmark['dataset_sha256']}`。", "",
                  "| 指标 | 本次结果 | 含义 |", "| --- | ---: | --- |",
                  f"| 三态准确率 | {percent(s['accuracy'])} | 包含信息不足、错误输出，不删失败样本 |",
                  f"| 宏平均 F1 | {s['macro_f1']:.3f} | 同时考察支持、矛盾、信息不足 |",
                  f"| 可判案例上的判断覆盖率 | {percent(s['decision_coverage'])} | 金标可判时实际作出支持/矛盾判断 |",
                  f"| 可判案例上的保留判断率 | {percent(s['abstention_on_decidable'])} | 缺能力也必须进入分母 |",
                  f"| 已作确定判断的正确率 | {percent(s['selective_accuracy'])} | 必须与覆盖率一起看 |",
                  f"| 错误确定判断 | {s['false_conclusive_count']}/{s['conclusive_cases']} | 非确定金标被过度断言也计错 |",
                  f"| 引用锚点有效率 | {percent(s['anchor_validity'])} | 只检验原文位置，不证明推理成立 |", "",
                  "| 子任务 | 案例数 | 准确率 | 可判覆盖率 |", "| --- | ---: | ---: | ---: |"]
        for aspect, data in benchmark["by_aspect"].items():
            lines.append(f"| {aspect} | {data['n_cases']} | {percent(data['accuracy'])} | {percent(data['decision_coverage'])} |")
        control = result["sanity_control"]["summary"]
        lines += ["", f"评分自检（始终回答信息不足，非模型基线）：准确率 {percent(control['accuracy'])}，宏F1 {control['macro_f1']:.3f}，判断覆盖率 {percent(control['decision_coverage'])}，确定判断正确率不适用。"]
        lines += ["", "未正确判断的案例：", ""]
        lines.extend(f"- `{r['case_id']}`：金标 `{r['gold']}`，输出 `{r['prediction']}`；{r['rationale']}。"
                     for r in benchmark["cases"] if not r["correct"])
        lines += ["", f"本机串行中位耗时 {benchmark['latency']['median_ms']:.1f} ms；最近秩 P95 {benchmark['latency']['nearest_rank_p95_ms']:.1f} ms。含本地保存，不含模型、网络、渲染；不可当作线上 SLA。"]
    lines += ["", "## 后续工作", "", "公开开发集上的修复通过不代表真实科研准确率。应冻结本轮代码与格式，再收集独立教师标注的留出材料、完成同模型基线对比。教学效果必须通过独立学生任务验证。完整协议见仓库 `docs/evaluation/plan.md`。", ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "evaluation" / "runs" / datetime.now().strftime("%Y%m%d-%H%M%S"))
    parser.add_argument("--skip-frontend", action="store_true")
    parser.add_argument("--release-gate", action="store_true", help="Exit 2 if known defects or test/build failures block release")
    parser.add_argument("--browser", action="store_true", help="Include isolated real headless browser workflow checks")
    args = parser.parse_args()
    if args.browser and args.skip_frontend:
        parser.error("--browser requires a fresh frontend build; do not combine with --skip-frontend")
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    # Never mutate dotenv; environment overrides prevent spending real provider credits.
    env = os.environ.copy()
    env.update(LLM_API_KEY="", LLM_BASE_URL="", LLM_MODEL="", PYTHONIOENCODING="utf-8",
               PYTHONPATH=os.pathsep.join((str(ROOT), str(ROOT / "backend"))))
    started = datetime.now(timezone.utc).isoformat()
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    fingerprint = source_hash()
    with tempfile.TemporaryDirectory(prefix="yanzheng-eval-") as temporary:
        env["DATA_DIR"] = str(Path(temporary) / "tests")
        stages = [run_stage("backend-tests", [sys.executable, "-m", "pytest", "tests", "system_tests", "-q", "-rxX",
                    "-o", "faulthandler_timeout=45", f"--junitxml={out / 'junit.xml'}"], ROOT / "backend", env, out)]
        audit = run_stage("known-defects-audit", [sys.executable, "-m", "pytest", "system_tests/test_known_defects.py",
            "-q", "--runxfail", f"--junitxml={out / 'known-defects.xml'}"], ROOT / "backend", env, out)
        audit["expected_exit_codes"] = [0]
        stages.append(audit)
        if not args.skip_frontend:
            npm = shutil.which("npm.cmd" if os.name == "nt" else "npm") or "npm"
            stages.append(run_stage("frontend-build", [npm, "run", "build"], ROOT / "frontend", env, out))
            stages.append(run_stage("frontend-lint", [npm, "run", "lint"], ROOT / "frontend", env, out))
        browser = None
        if args.browser:
            browser_directory = out / "browser"
            browser_directory.mkdir(exist_ok=True)
            (browser_directory / "results.json").unlink(missing_ok=True)
            env["YANZHENG_BROWSER_REPORT_DIR"] = str(browser_directory)
            stages.append(run_stage("browser-tests", [sys.executable, "-m", "evaluation.run_browser"], ROOT, env, out))
            browser = browser_summary(browser_directory / "results.json")
        os.environ.update(LLM_API_KEY="", LLM_BASE_URL="", LLM_MODEL="", DATA_DIR=str(Path(temporary) / "benchmark"))
        sys.path.insert(0, str(ROOT / "backend"))
        from .benchmark import run_offline
        benchmark = run_offline(ROOT / "evaluation" / "cases.json", Path(temporary) / "benchmark")
        from .prepare import prepare
        from .score import score
        prepare(ROOT / "evaluation" / "cases.json", out / "input-pack")
        sanity = score(ROOT / "evaluation" / "cases.json", out / "input-pack" / "all-insufficient-control.json")
    test_counts = junit_summary(out / "junit.xml")
    operational_failures = [s["name"] for s in stages if s["exit_code"] not in s.get("expected_exit_codes", [0])]
    blockers = operational_failures + [x["reason"] for x in test_counts.get("known_defects", [])]
    release_gate = {"passed": not blockers, "blockers": blockers,
                    "scope": "local_regression_only_not_real_world_or_learning_validation"}
    result = dict(started_at_utc=started, source_commit=commit, source_sha256=fingerprint,
                  python_version=sys.version.split()[0], provider_calls=0, production_requests=0,
                  stages=stages, tests=test_counts, benchmark=benchmark,
                  sanity_control=sanity, known_defect_audit=junit_summary(out / "known-defects.xml"), release_gate=release_gate)
    if browser is not None:
        result["browser"] = browser
        (out / "browser-summary.json").write_text(json.dumps(browser, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    result["package_versions"] = {name: importlib.metadata.version(name)
        for name in ("pytest", "fastapi", "pydantic", "httpx", "starlette", "anyio")}
    (out / "results.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    (out / "summary.md").write_text(markdown(result), encoding="utf-8")
    print(json.dumps({"output": str(out), "tests": result["tests"],
                      "stage_exit_codes": {s['name']: s['exit_code'] for s in stages},
                      "probe_accuracy": benchmark["summary"]["accuracy"],
                      "decision_coverage": benchmark["summary"]["decision_coverage"]}, ensure_ascii=True))
    # Zero means execution stages succeeded, not that known defects or capability gaps are gone.
    if args.release_gate and not release_gate["passed"]:
        return 2
    return 1 if operational_failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
