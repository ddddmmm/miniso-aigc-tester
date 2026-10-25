#!/usr/bin/env python3
"""
HTML 测试报告生成（report）：汇总运行日志 + 打分表，生成自包含 HTML。

产物：
  reports/report_<run_id>.html   图片以 base64 内嵌，单文件可直接分发
  reports/report_<run_id>.json   机读数据，供下次生成时做回归对比

回归对比：与上一次报告比较同一用例的平均分，分数下降即退化，标红。
"""

import base64
import html as html_lib
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from .review import (
    dimensions_for_scene,
    find_latest_log,
    find_review_for_run,
    is_pass,
    load_review_sheet,
    load_run_records,
    mean_score,
    PASS_THRESHOLD,
)


def image_to_data_uri(path: str) -> Optional[str]:
    """把图片转成 base64 data URI（找不到文件返回 None）。"""
    p = Path(path)
    if not p.exists():
        return None
    data = p.read_bytes()
    b64 = base64.b64encode(data).decode("ascii")
    return f"data:image/png;base64,{b64}"


def case_final_map(records: List[dict]) -> Dict[str, dict]:
    """每个用例取最后一轮记录（用于用例级统计）。"""
    result: Dict[str, dict] = {}
    for r in records:
        cid = r["case_id"]
        if cid not in result or r.get("round", 0) > result[cid].get("round", 0):
            result[cid] = r
    return result


def find_previous_report_json(run_id: str, reports_dir: str = "reports") -> Optional[Path]:
    """找到 run_id 之前最近一次报告的 JSON。"""
    files = sorted(Path(reports_dir).glob("report_*.json"))
    previous = [f for f in files if run_id not in f.name]
    return previous[-1] if previous else None


def _status_badge(status: str) -> str:
    icons = {
        "success": '<span class="pass">✅ 通过</span>',
        "failed": '<span class="fail">❌ 失败</span>',
        "skipped": '<span class="skip">⏭️ 跳过</span>',
    }
    return icons.get(status, status)


def _score_chips(scores: Dict[str, int], dims: Dict[str, str]) -> str:
    """渲染各维度分数小标签。"""
    chips = []
    for key, label in dims.items():
        value = scores.get(key, "-")
        cls = "score-low" if isinstance(value, int) and value <= 2 else "score"
        chips.append(f'<span class="{cls}" title="{html_lib.escape(label)}">{value}</span>')
    return "".join(chips)


def build_html(
    records: List[dict],
    review_sheet: Optional[dict],
    run_id: str,
    log_path: str,
    prev_means: Optional[Dict[str, float]],
) -> str:
    """构建完整 HTML 字符串。"""
    review_index = {}
    if review_sheet:
        for rv in review_sheet["reviews"]:
            review_index[(rv["case_id"], rv["round"])] = rv

    # ---------- 用例级统计 ----------
    final_map = case_final_map(records)
    effective_cases = {cid: r for cid, r in final_map.items() if r["status"] != "skipped"}
    passed_cases = 0
    for cid, r in effective_cases.items():
        if r["status"] == "success":
            rv = review_index.get((cid, r.get("round", 1)))
            if rv is None or rv.get("pass", False):
                passed_cases += 1
    total_effective = len(effective_cases)
    pass_rate = round(passed_cases / total_effective * 100, 1) if total_effective else 0.0
    skipped_count = sum(1 for r in final_map.values() if r["status"] == "skipped")

    # ---------- 维度平均分（用最后一轮） ----------
    dim_sums = defaultdict(lambda: [0, 0])
    for cid, r in final_map.items():
        if r["status"] != "success":
            continue
        rv = review_index.get((cid, r.get("round", 1)))
        if not rv:
            continue
        for key, value in rv["scores"].items():
            dim_sums[key][0] += value
            dim_sums[key][1] += 1

    dim_avg_rows = []
    all_dims = {}
    for r in final_map.values():
        all_dims.update(dimensions_for_scene(r.get("scene", "")))
    for key, label in all_dims.items():
        total, count = dim_sums.get(key, [0, 0])
        avg = round(total / count, 2) if count else "-"
        dim_avg_rows.append(
            f"<tr><td>{html_lib.escape(label)}</td><td><b>{avg}</b></td><td>{count}</td></tr>"
        )

    # ---------- 用例表格 ----------
    table_rows = []
    current_means_for_regression: Dict[str, float] = {}
    for r in records:
        cid = r["case_id"]
        round_no = r.get("round", 1)
        reg_key = f"{cid}#r{round_no}"
        rv = review_index.get((cid, round_no))
        scores = rv["scores"] if rv else {}
        mean = mean_score(scores) if scores else None
        if mean is not None:
            current_means_for_regression[reg_key] = mean

        # 回归判定
        regression = False
        prev_mean = prev_means.get(reg_key) if prev_means is not None else None
        if prev_mean is not None and mean is not None and mean < prev_mean:
            regression = True
        row_cls = ' class="regression"' if regression else ""

        image_cell = ""
        if r["status"] == "success" and r.get("output"):
            uri = image_to_data_uri(r["output"])
            if uri:
                image_cell = f'<img class="thumb" src="{uri}" alt="{cid}">'
        elif r["status"] == "failed":
            image_cell = '<span class="fail">—</span>'

        request = r.get("request", {})
        params_text = f"{request.get('model','')} / {request.get('size','')}"
        dims = dimensions_for_scene(r.get("scene", ""))
        score_cell = _score_chips(scores, dims) if scores else ""
        if mean is not None:
            score_cell += f'<div class="mean">均分 {mean}</div>'
        if regression:
            score_cell += f'<div class="fail">↓ 上次 {prev_mean}，退化</div>'

        problem_text = ""
        if r["status"] == "failed":
            problem_text = html_lib.escape(r.get("error") or "")
        elif rv and rv.get("problems"):
            problem_text = "<br>".join(html_lib.escape(p) for p in rv["problems"])

        table_rows.append(
            f"<tr{row_cls}><td>{cid}<br><span class='round'>第{round_no}轮</span></td>"
            f"<td>{html_lib.escape(r.get('scene',''))}</td>"
            f"<td class='small'>{html_lib.escape(params_text)}</td>"
            f"<td>{image_cell}</td>"
            f"<td>{score_cell}</td>"
            f"<td class='small'>{problem_text}</td></tr>"
        )

    # ---------- 问题清单 ----------
    problem_items = []
    for r in records:
        if r["status"] == "failed":
            problem_items.append(
                f'<div class="problem"><b>{r["case_id"]}</b>（执行失败）：'
                f'{html_lib.escape(r.get("error") or "")}</div>'
            )
    for rv in (review_sheet["reviews"] if review_sheet else []):
        for p in rv.get("problems", []):
            problem_items.append(
                f'<div class="problem"><b>{rv["case_id"]} 第{rv["round"]}轮</b>'
                f'（复核问题）：{html_lib.escape(p)}</div>'
            )
    problems_html = "\n".join(problem_items) or '<div class="ok">✅ 无遗留问题</div>'

    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>MINISO AIGC 测试报告 - {run_id}</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{ font-family: -apple-system, "Segoe UI", "Microsoft YaHei", sans-serif;
         margin: 0; background: #f5f5f7; color: #1d1d1f; }}
  .container {{ max-width: 1180px; margin: 0 auto; padding: 32px 24px 60px; }}
  h1 {{ font-size: 26px; margin: 0 0 4px; }}
  h1 .brand {{ color: #e60012; }}
  .sub {{ color: #6e6e73; font-size: 13px; margin-bottom: 24px; }}
  h2 {{ font-size: 18px; margin: 36px 0 14px; }}
  .cards {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; }}
  .card {{ background: #fff; border-radius: 14px; padding: 20px; box-shadow: 0 1px 3px rgba(0,0,0,.07); }}
  .card .label {{ color: #6e6e73; font-size: 13px; }}
  .card .value {{ font-size: 34px; font-weight: 700; margin-top: 6px; }}
  .card .value.red {{ color: #dc2626; }}
  .card .value.green {{ color: #16a34a; }}
  table {{ width: 100%; border-collapse: collapse; background: #fff;
           border-radius: 14px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,.07); }}
  th, td {{ padding: 12px 14px; text-align: left; border-bottom: 1px solid #f0f0f2;
            vertical-align: top; font-size: 13px; }}
  th {{ background: #fafafa; font-weight: 600; white-space: nowrap; }}
  .small {{ font-size: 12px; color: #444; }}
  .round {{ color: #6e6e73; font-size: 11px; }}
  .pass {{ color: #16a34a; font-weight: 600; }}
  .fail {{ color: #dc2626; font-weight: 600; }}
  .skip {{ color: #b45309; font-weight: 600; }}
  .ok {{ color: #16a34a; }}
  .regression {{ background: #fef2f2; }}
  .thumb {{ width: 130px; border-radius: 8px; border: 1px solid #eee; }}
  .score, .score-low {{ display: inline-block; min-width: 26px; text-align: center;
           padding: 2px 6px; border-radius: 6px; margin: 1px; background: #eef6ff; font-size: 12px; }}
  .score-low {{ background: #fee2e2; color: #dc2626; font-weight: 700; }}
  .mean {{ margin-top: 6px; font-size: 12px; color: #1d1d1f; }}
  .problem {{ background: #fff; border-left: 4px solid #dc2626; padding: 10px 14px;
              margin-bottom: 8px; border-radius: 6px; font-size: 13px;
              box-shadow: 0 1px 2px rgba(0,0,0,.05); }}
  .dimtable {{ width: auto; min-width: 320px; }}
  a {{ color: #0066cc; }}
</style>
</head>
<body>
<div class="container">
  <h1><span class="brand">MINISO</span> 品牌营销 AIGC 测试报告</h1>
  <div class="sub">运行批次 run_id：{run_id} ｜ 报告生成时间：{generated_at} ｜
    日志文件：{html_lib.escape(log_path)}</div>

  <div class="cards">
    <div class="card"><div class="label">用例通过率（执行用例）</div>
      <div class="value {'green' if pass_rate >= 80 else 'red'}">{pass_rate}%</div></div>
    <div class="card"><div class="label">通过 / 执行用例</div>
      <div class="value">{passed_cases}/{total_effective}</div></div>
    <div class="card"><div class="label">跳过用例（未启用）</div>
      <div class="value">{skipped_count}</div></div>
    <div class="card"><div class="label">通过判定阈值</div>
      <div class="value">≥ {PASS_THRESHOLD}</div></div>
  </div>

  <h2>各维度平均分</h2>
  <table class="dimtable">
    <tr><th>复核维度</th><th>平均分</th><th>样本数</th></tr>
    {''.join(dim_avg_rows)}
  </table>

  <h2>用例执行与复核明细</h2>
  <table>
    <tr><th>用例ID</th><th>场景</th><th>参数</th><th>效果图</th><th>维度分数</th><th>问题记录</th></tr>
    {''.join(table_rows)}
  </table>

  <h2>问题清单（需跟进）</h2>
  {problems_html}
</div>
</body>
</html>
"""


def generate_report(
    log_path: Optional[str] = None,
    reports_dir: str = "reports",
) -> dict:
    """生成报告的入口函数。

    Returns:
        汇总信息：html_path、run_id、pass_rate 等。
    """
    log_file = Path(log_path) if log_path else find_latest_log()
    if log_file is None:
        raise FileNotFoundError("未找到运行日志，请先执行 aigc run")

    records = load_run_records(log_file)
    run_id = records[0]["run_id"]

    # 找对应打分表（不存在则只按执行结果生成）
    review_path = find_review_for_run(run_id)
    review_sheet = load_review_sheet(review_path) if review_path else None

    # 回归对比：读取上一次报告的 JSON
    prev_json = find_previous_report_json(run_id, reports_dir)
    prev_means = None
    if prev_json:
        with open(prev_json, encoding="utf-8") as f:
            prev_data = json.load(f)
        prev_means = prev_data.get("means")

    html_text = build_html(
        records,
        review_sheet,
        run_id,
        str(log_file).replace("\\", "/"),
        prev_means,
    )

    out_dir = Path(reports_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    html_path = out_dir / f"report_{run_id}.html"
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html_text)

    # 写机读 JSON（供下次回归对比）
    final_map = case_final_map(records)
    means = {}
    if review_sheet:
        for rv in review_sheet["reviews"]:
            means[f"{rv['case_id']}#r{rv['round']}"] = mean_score(rv["scores"])
    json_path = out_dir / f"report_{run_id}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({"run_id": run_id, "means": means, "generated_at": datetime.now().isoformat()},
                  f, ensure_ascii=False, indent=2)

    return {
        "html_path": str(html_path).replace("\\", "/"),
        "json_path": str(json_path).replace("\\", "/"),
        "run_id": run_id,
        "has_reviews": review_sheet is not None,
    }
