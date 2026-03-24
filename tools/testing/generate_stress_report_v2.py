#!/usr/bin/env python3
"""
Generate HTML Stress Test Report v2 — Quality Score as Primary Metric.

Reads .tmp/stress_test_v2_results.json and generates a rich HTML report with:
- quality_score as the main grade (not raw retrieval similarity)
- Answer text visible per question
- LLM evaluation breakdown (relevancia / fidelidad / exhaustividad)
- Side-by-side comparison: quality_score vs retrieval_score
- Visual highlight when quality >> retrieval (good RAG, thin data)

Usage:
    PYTHONPATH=. python tools/testing/generate_stress_report_v2.py
"""

import json
import html
from pathlib import Path


def load_data():
    path = Path(".tmp/stress_test_v2_results.json")
    if not path.exists():
        raise FileNotFoundError("Run stress_test_v2.py first to generate .tmp/stress_test_v2_results.json")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def score_color(score):
    if score >= 0.75: return "#22c55e"   # green
    if score >= 0.60: return "#3b82f6"   # blue
    if score >= 0.45: return "#eab308"   # yellow
    if score >= 0.30: return "#f97316"   # orange
    return "#ef4444"                      # red


def grade(pct):
    if pct >= 85: return "A+", "#10b981"
    if pct >= 75: return "A",  "#22c55e"
    if pct >= 65: return "B+", "#3b82f6"
    if pct >= 55: return "B",  "#60a5fa"
    if pct >= 45: return "C",  "#eab308"
    if pct >= 35: return "D",  "#f97316"
    return "F", "#ef4444"


CAT_LABELS = {
    "simple": "Simples e Diretas",
    "country": "Filtros por País",
    "bandera": "Filtros por Bandera",
    "team": "Filtros por Team",
    "complex": "Complexas Multi-dim",
    "portuguese": "Português",
    "edge": "Edge Cases",
}


def bar(value_0_to_10, color, label=""):
    """Mini SVG progress bar for eval scores."""
    pct = min(max(value_0_to_10 * 10, 0), 100)
    return (
        f'<div style="display:flex;align-items:center;gap:6px;margin:2px 0">'
        f'<span style="font-size:11px;color:#94a3b8;width:90px;flex-shrink:0">{label}</span>'
        f'<div style="flex:1;background:#1e293b;border-radius:3px;height:8px">'
        f'<div style="width:{pct}%;background:{color};height:8px;border-radius:3px"></div></div>'
        f'<span style="font-size:11px;color:{color};width:20px;text-align:right">{value_0_to_10}</span>'
        f'</div>'
    )


def generate_html(data):
    results = data["results"]
    eval_enabled = data.get("eval_enabled", True)

    # ── Category stats ────────────────────────────────────────────────
    cats = {}
    for r in results:
        cat = r["category"]
        if cat not in cats:
            cats[cat] = {"quality": [], "retrieval": [], "answered": 0, "total": 0}
        cats[cat]["total"] += 1
        if r.get("metrics", {}).get("chunk_count", 0) > 0:
            cats[cat]["answered"] += 1
            cats[cat]["retrieval"].append(r.get("retrieval_score", 0))
            if r.get("quality_score", 0) > 0:
                cats[cat]["quality"].append(r["quality_score"])

    # ── Global stats ──────────────────────────────────────────────────
    answered = [r for r in results if r.get("metrics", {}).get("chunk_count", 0) > 0]
    q_scores = [r["quality_score"] for r in answered if r.get("quality_score", 0) > 0]
    r_scores = [r["retrieval_score"] for r in answered if r.get("retrieval_score") is not None]
    avg_quality = sum(q_scores) / max(len(q_scores), 1)
    avg_retrieval = sum(r_scores) / max(len(r_scores), 1)
    avg_latency = sum(r.get("metrics", {}).get("latency_total_s", 0) for r in results) / max(len(results), 1)
    g, gc = grade(avg_quality * 100)

    # Eval averages
    eval_sums = {"relevancia": 0, "fidelidad": 0, "exhaustividad": 0}
    eval_count = 0
    for r in answered:
        ev = r.get("eval", {})
        if ev and "relevancia" in ev:
            eval_sums["relevancia"] += ev["relevancia"]
            eval_sums["fidelidad"] += ev["fidelidad"]
            eval_sums["exhaustividad"] += ev["exhaustividad"]
            eval_count += 1
    eval_avgs = {k: round(v / max(eval_count, 1), 1) for k, v in eval_sums.items()}

    # ── HTML ──────────────────────────────────────────────────────────
    parts = [f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="UTF-8">
<title>Stress Test v2 — RAG Quality Report</title>
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #0f172a; color: #e2e8f0; max-width: 1200px; margin: 0 auto; padding: 24px; }}
h1 {{ font-size: 26px; margin-bottom: 6px; color: #f1f5f9; }}
h2 {{ font-size: 18px; margin: 28px 0 10px; color: #94a3b8; border-bottom: 1px solid #334155; padding-bottom: 6px; }}
.meta {{ color: #64748b; font-size: 13px; margin-bottom: 20px; }}
.badge-new {{ background: #1d4ed8; color: #bfdbfe; font-size: 11px; padding: 2px 8px; border-radius: 10px; margin-left: 8px; }}
.dashboard {{ display: grid; grid-template-columns: repeat(5, 1fr); gap: 10px; margin: 18px 0; }}
.stat {{ background: #1e293b; border-radius: 10px; padding: 14px; text-align: center; }}
.stat .value {{ font-size: 26px; font-weight: 700; }}
.stat .label {{ font-size: 11px; color: #64748b; margin-top: 4px; }}
.grade-box {{ background: #1e293b; border-radius: 14px; padding: 20px; margin: 18px 0; display: flex; align-items: center; gap: 20px; }}
.grade-big {{ font-size: 72px; font-weight: 900; line-height: 1; }}
.grade-detail {{ flex: 1; }}
.score-compare {{ display: flex; gap: 10px; margin-top: 8px; }}
.score-tag {{ padding: 4px 12px; border-radius: 6px; font-size: 13px; font-weight: 600; }}
.eval-bars {{ display: flex; flex-direction: column; gap: 4px; margin-top: 8px; }}
.cat-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 10px; margin: 12px 0; }}
.cat-card {{ background: #1e293b; border-radius: 8px; padding: 14px; }}
.cat-card .name {{ font-size: 12px; color: #94a3b8; margin-bottom: 6px; }}
.cat-scores {{ display: flex; align-items: center; gap: 10px; }}
.cat-q {{ font-size: 22px; font-weight: 700; }}
.cat-r {{ font-size: 14px; color: #64748b; }}
.delta-up {{ color: #22c55e; font-size: 11px; font-weight: 600; }}
.delta-dn {{ color: #ef4444; font-size: 11px; font-weight: 600; }}
.question {{ background: #1e293b; border-radius: 12px; padding: 18px; margin: 14px 0; border-left: 4px solid #334155; }}
.question.high {{ border-left-color: #22c55e; }}
.question.med  {{ border-left-color: #3b82f6; }}
.question.low  {{ border-left-color: #eab308; }}
.question.fail {{ border-left-color: #ef4444; }}
.question.boost {{ border: 1px solid #22c55e44; }}
.q-header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; flex-wrap: wrap; gap: 6px; }}
.q-id {{ background: #334155; color: #94a3b8; padding: 2px 10px; border-radius: 12px; font-size: 12px; font-weight: 600; }}
.q-scores {{ display: flex; align-items: center; gap: 10px; }}
.q-quality {{ font-size: 20px; font-weight: 700; }}
.q-retrieval {{ font-size: 13px; color: #64748b; }}
.q-text {{ font-size: 15px; font-weight: 600; color: #f1f5f9; margin-bottom: 12px; }}
.filters {{ color: #f59e0b; font-size: 12px; margin-bottom: 8px; }}
.answer-box {{ background: #0f172a; border-radius: 8px; padding: 14px; margin: 10px 0; font-size: 14px; line-height: 1.7; color: #cbd5e1; white-space: pre-wrap; max-height: 280px; overflow-y: auto; }}
.eval-section {{ background: #0f172a; border-radius: 8px; padding: 12px; margin: 8px 0; }}
.eval-title {{ font-size: 12px; color: #64748b; margin-bottom: 8px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; }}
.eval-justify {{ font-size: 12px; color: #64748b; margin-top: 8px; font-style: italic; }}
.boost-tag {{ background: #14532d; color: #86efac; font-size: 11px; padding: 2px 8px; border-radius: 8px; margin-left: 6px; }}
.chunk {{ background: #0f172a; border-radius: 6px; padding: 9px 12px; margin: 5px 0; font-size: 12px; display: flex; gap: 10px; }}
.chunk .score-pill {{ min-width: 50px; font-weight: 600; flex-shrink: 0; }}
.chunk .file {{ color: #94a3b8; flex: 1; }}
.chunk .meta-tags {{ color: #64748b; font-size: 11px; }}
.chunk .preview {{ color: #475569; font-size: 11px; margin-top: 3px; }}
.metrics {{ display: flex; gap: 12px; margin-top: 10px; flex-wrap: wrap; font-size: 12px; color: #64748b; }}
.metrics span {{ background: #0f172a; padding: 2px 8px; border-radius: 4px; }}
.no-results {{ color: #ef4444; font-style: italic; padding: 10px; }}
</style></head><body>
<h1>Stress Test Report v2 <span class="badge-new">LLM-as-Judge</span></h1>
<div class="meta">{data.get('test_date', '')} | {data.get('vector_count', 0):,} vectors | {data.get('index', '')} | {data.get('llm_model', 'gemini')}</div>

<div class="grade-box">
  <div class="grade-big" style="color:{gc}">{g}</div>
  <div class="grade-detail">
    <div style="font-size:16px;color:#f1f5f9;margin-bottom:6px">Quality Score: <strong style="color:{gc}">{avg_quality:.3f}</strong></div>
    <div class="score-compare">
      <span class="score-tag" style="background:#1d4ed822;color:#60a5fa">Quality: {avg_quality:.3f}</span>
      <span class="score-tag" style="background:#33415522;color:#64748b">Retrieval: {avg_retrieval:.3f}</span>
      <span class="score-tag" style="background:#14532d22;color:#86efac">{len(answered)}/{len(results)} respondidas</span>
    </div>
    {'<div class="eval-bars">' + bar(eval_avgs["relevancia"], "#60a5fa", "Relevância avg") + bar(eval_avgs["fidelidad"], "#22c55e", "Fidelidade avg") + bar(eval_avgs["exhaustividad"], "#a78bfa", "Exhaustividade avg") + '</div>' if eval_enabled else ''}
  </div>
</div>

<div class="dashboard">
  <div class="stat"><div class="value" style="color:{score_color(avg_quality)}">{avg_quality:.3f}</div><div class="label">Quality Score</div></div>
  <div class="stat"><div class="value" style="color:{score_color(avg_retrieval)}">{avg_retrieval:.3f}</div><div class="label">Retrieval Score</div></div>
  <div class="stat"><div class="value" style="color:#60a5fa">{eval_avgs['relevancia']}/10</div><div class="label">Relevância LLM</div></div>
  <div class="stat"><div class="value" style="color:#22c55e">{eval_avgs['fidelidad']}/10</div><div class="label">Fidelidade LLM</div></div>
  <div class="stat"><div class="value">{avg_latency:.1f}s</div><div class="label">Latência Média</div></div>
</div>

<h2>Por Categoria</h2>
<div class="cat-grid">"""]

    for cat_key, cat_label in CAT_LABELS.items():
        cd = cats.get(cat_key, {"quality": [], "retrieval": [], "answered": 0, "total": 0})
        cq = sum(cd["quality"]) / max(len(cd["quality"]), 1)
        cr = sum(cd["retrieval"]) / max(len(cd["retrieval"]), 1)
        delta = cq - cr
        delta_str = (
            f'<span class="delta-up">▲ +{delta:.3f}</span>' if delta > 0.01
            else f'<span class="delta-dn">▼ {delta:.3f}</span>' if delta < -0.01
            else '<span style="color:#64748b">≈</span>'
        )
        parts.append(f"""<div class="cat-card">
  <div class="name">{cat_label} — {cd['answered']}/{cd['total']}</div>
  <div class="cat-scores">
    <div class="cat-q" style="color:{score_color(cq)}">{cq:.3f}</div>
    {delta_str}
    <div class="cat-r">ret: {cr:.3f}</div>
  </div>
</div>""")

    parts.append("</div><h2>Detalhe por Pergunta</h2>")

    for r in results:
        qs = r.get("quality_score", 0)
        rs = r.get("retrieval_score", 0)
        ev = r.get("eval", {})
        answer = r.get("answer", "")
        chunks = r.get("chunks", [])
        filters = r.get("filters_applied", {})

        # Classify question
        if qs >= 0.75:
            cls = "high"
        elif qs >= 0.60:
            cls = "med"
        elif qs >= 0.40:
            cls = "low"
        else:
            cls = "fail"

        # Boost tag: quality much better than retrieval
        boost = (qs - rs) > 0.10

        filter_str = ""
        if filters:
            fp = []
            if "$and" in filters:
                for cond in filters["$and"]:
                    for k, v in cond.items():
                        if isinstance(v, dict) and "$eq" in v:
                            fp.append(f"{k}={v['$eq']}")
            else:
                for k, v in filters.items():
                    if isinstance(v, dict) and "$eq" in v:
                        fp.append(f"{k}={v['$eq']}")
            if fp:
                filter_str = f'<div class="filters">⚡ Filtros: {", ".join(fp)}</div>'

        boost_cls = " boost" if boost else ""
        boost_tag = '<span class="boost-tag">↑ RAG bom, base pequena</span>' if boost else ""
        delta_qs = qs - rs
        delta_color = "#22c55e" if delta_qs > 0 else "#ef4444"
        delta_display = f'+{delta_qs:.3f}' if delta_qs >= 0 else f'{delta_qs:.3f}'

        parts.append(f"""<div class="question {cls}{boost_cls}">
  <div class="q-header">
    <div>
      <span class="q-id">Q{r['question_id']} | {CAT_LABELS.get(r['category'], r['category'])}</span>
      {boost_tag}
    </div>
    <div class="q-scores">
      <span class="q-quality" style="color:{score_color(qs)}">{qs:.3f}</span>
      <span class="q-retrieval">ret: {rs:.3f} <span style="color:{delta_color};font-size:11px">({delta_display})</span></span>
    </div>
  </div>
  <div class="q-text">{html.escape(r['question'])}</div>
  {filter_str}""")

        # Answer
        if answer:
            parts.append(f'<div class="answer-box">{html.escape(answer)}</div>')

        # Eval breakdown
        if ev and "relevancia" in ev and eval_enabled:
            just = html.escape(ev.get("justificacion", ""))
            parts.append(f"""<div class="eval-section">
  <div class="eval-title">Avaliação LLM</div>
  {bar(ev['relevancia'], "#60a5fa", "Relevância")}
  {bar(ev['fidelidad'], "#22c55e", "Fidelidade")}
  {bar(ev['exhaustividad'], "#a78bfa", "Exhaustividade")}
  <div class="eval-justify">{just}</div>
</div>""")

        # Chunks
        if chunks:
            parts.append('<h3 style="font-size:13px;color:#64748b;margin:10px 0 4px">Chunks recuperados</h3>')
            for c in chunks[:5]:
                sc = c.get("score", 0)
                fname = html.escape(c.get("file_name", "?")[:60])
                country = c.get("country", "")
                bandera = c.get("bandera", "")
                team = c.get("team", "")
                fecha = c.get("fecha", "")
                preview = html.escape(c.get("text", "")[:120])
                parts.append(f"""<div class="chunk">
  <span class="score-pill" style="color:{score_color(sc)}">{sc:.3f}</span>
  <div>
    <div class="file">{fname}</div>
    <div class="meta-tags">{country} | {bandera} | {team} | {fecha}</div>
    <div class="preview">{preview}…</div>
  </div>
</div>""")
        else:
            parts.append('<div class="no-results">Sem resultados — filtro restritivo ou dados insuficientes</div>')

        # Footer metrics
        m = r.get("metrics", {})
        met_parts = []
        if m.get("unique_files"): met_parts.append(f"<span>{m['unique_files']} arquivos</span>")
        if m.get("text_chunks") is not None: met_parts.append(f"<span>{m.get('text_chunks',0)} txt / {m.get('image_chunks',0)} img</span>")
        if m.get("filter_accuracy") is not None: met_parts.append(f"<span>Filter acc: {m['filter_accuracy']*100:.0f}%</span>")
        if m.get("latency_total_s"): met_parts.append(f"<span>{m['latency_total_s']:.1f}s</span>")
        if met_parts:
            parts.append(f'<div class="metrics">{"".join(met_parts)}</div>')

        parts.append("</div>")

    parts.append("""
<div style="margin-top:30px;padding:16px;background:#1e293b;border-radius:10px;font-size:13px;color:#64748b">
  <strong style="color:#94a3b8">Como ler o Quality Score:</strong>
  quality = 0.3 × retrieval + 0.4 × relevância + 0.3 × fidelidade &nbsp;|&nbsp;
  <span style="color:#22c55e">▲ RAG bom, base pequena</span> = quality &gt;&gt; retrieval (dados escassos mas resposta correta)
</div>
</body></html>""")

    return "\n".join(parts)


if __name__ == "__main__":
    data = load_data()
    html_content = generate_html(data)
    out = Path(".tmp/stress_test_v2_report.html")
    out.write_text(html_content, encoding="utf-8")
    print(f"Report generated: {out}")
