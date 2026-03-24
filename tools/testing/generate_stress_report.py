#!/usr/bin/env python3
"""
Generate HTML Stress Test Report from retrieval results + Claude-generated answers.

Usage:
    PYTHONPATH=. python tools/testing/generate_stress_report.py
"""

import json
import html
from pathlib import Path

def load_data():
    with open(".tmp/stress_test_report.json", encoding="utf-8") as f:
        return json.load(f)

def score_color(score):
    if score >= 0.7: return "#22c55e"
    if score >= 0.5: return "#eab308"
    if score >= 0.3: return "#f97316"
    return "#ef4444"

def grade(pct):
    if pct >= 80: return "A", "#22c55e"
    if pct >= 60: return "B", "#3b82f6"
    if pct >= 40: return "C", "#eab308"
    return "D", "#ef4444"

def generate_html(data):
    results = data["results"]
    meta = data.get("meta", {})

    # Compute category stats
    cats = {}
    for r in results:
        cat = r["category"]
        if cat not in cats:
            cats[cat] = {"scores": [], "answered": 0, "total": 0}
        cats[cat]["total"] += 1
        m = r.get("metrics", {})
        if m.get("chunk_count", 0) > 0:
            cats[cat]["answered"] += 1
            cats[cat]["scores"].append(m.get("avg_score", 0))

    # Global stats
    all_scores = [r["metrics"]["avg_score"] for r in results if r["metrics"].get("chunk_count", 0) > 0]
    answered = sum(1 for r in results if r["metrics"].get("chunk_count", 0) > 0)
    avg_score = sum(all_scores) / max(len(all_scores), 1)
    avg_latency = sum(r["metrics"].get("latency_total_s", 0) for r in results) / max(len(results), 1)
    global_pct = (avg_score * 100)
    g, gc = grade(global_pct)

    cat_names = {
        "simple": "Simples e Diretas",
        "country": "Filtros por Pais",
        "bandera": "Filtros por Bandera",
        "team": "Filtros por Team",
        "complex": "Complexas Multi-dim",
        "portuguese": "Portugues",
        "edge": "Edge Cases",
    }

    html_parts = [f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="UTF-8">
<title>Stress Test Report — RAG Genova</title>
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #0f172a; color: #e2e8f0; max-width: 1100px; margin: 0 auto; padding: 20px; }}
h1 {{ font-size: 28px; margin-bottom: 8px; color: #f1f5f9; }}
h2 {{ font-size: 20px; margin: 30px 0 12px; color: #94a3b8; border-bottom: 1px solid #334155; padding-bottom: 8px; }}
h3 {{ font-size: 16px; margin: 20px 0 8px; color: #cbd5e1; }}
.meta {{ color: #64748b; font-size: 13px; margin-bottom: 20px; }}
.dashboard {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin: 20px 0; }}
.stat {{ background: #1e293b; border-radius: 10px; padding: 16px; text-align: center; }}
.stat .value {{ font-size: 28px; font-weight: 700; }}
.stat .label {{ font-size: 12px; color: #64748b; margin-top: 4px; }}
.grade {{ font-size: 64px; font-weight: 900; text-align: center; padding: 20px; border-radius: 16px; background: #1e293b; margin: 20px 0; }}
.cat-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 10px; margin: 12px 0; }}
.cat-card {{ background: #1e293b; border-radius: 8px; padding: 12px; }}
.cat-card .name {{ font-size: 13px; color: #94a3b8; }}
.cat-card .score {{ font-size: 22px; font-weight: 700; }}
.question {{ background: #1e293b; border-radius: 12px; padding: 18px; margin: 16px 0; border-left: 4px solid #334155; }}
.question.high {{ border-left-color: #22c55e; }}
.question.mid {{ border-left-color: #eab308; }}
.question.low {{ border-left-color: #ef4444; }}
.q-header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }}
.q-id {{ background: #334155; color: #94a3b8; padding: 2px 10px; border-radius: 12px; font-size: 12px; font-weight: 600; }}
.q-score {{ font-size: 18px; font-weight: 700; }}
.q-text {{ font-size: 15px; font-weight: 600; color: #f1f5f9; margin-bottom: 12px; }}
.answer {{ background: #0f172a; border-radius: 8px; padding: 14px; margin: 10px 0; font-size: 14px; line-height: 1.6; color: #cbd5e1; white-space: pre-wrap; }}
.chunk {{ background: #0f172a; border-radius: 6px; padding: 10px 12px; margin: 6px 0; font-size: 12px; display: flex; gap: 10px; }}
.chunk .badge {{ min-width: 40px; text-align: center; padding: 2px 8px; border-radius: 4px; font-weight: 700; font-size: 11px; }}
.chunk .badge.txt {{ background: #1e3a5f; color: #60a5fa; }}
.chunk .badge.img {{ background: #3b1f4b; color: #c084fc; }}
.chunk .score-pill {{ min-width: 50px; font-weight: 600; }}
.chunk .file {{ color: #94a3b8; flex: 1; }}
.chunk .meta-tags {{ color: #64748b; font-size: 11px; }}
.chunk .preview {{ color: #475569; font-size: 11px; margin-top: 4px; }}
.metrics {{ display: flex; gap: 16px; margin-top: 10px; font-size: 12px; color: #64748b; }}
.metrics span {{ background: #0f172a; padding: 2px 8px; border-radius: 4px; }}
.filters {{ color: #f59e0b; font-size: 12px; margin-bottom: 6px; }}
.no-results {{ color: #ef4444; font-style: italic; padding: 10px; }}
</style></head><body>
<h1>Stress Test Report — RAG Genova</h1>
<div class="meta">{meta.get('test_date', '')} | {meta.get('vector_count', 0):,} vectors | Index: {meta.get('index', '')} | Model: {meta.get('embedding_model', '')} ({meta.get('embedding_dims', 0)} dims)</div>

<div class="grade" style="color:{gc}">Score: {g} ({global_pct:.0f}%)</div>

<div class="dashboard">
  <div class="stat"><div class="value" style="color:{score_color(avg_score)}">{avg_score:.3f}</div><div class="label">Retrieval Score Medio</div></div>
  <div class="stat"><div class="value">{answered}/{len(results)}</div><div class="label">Perguntas Respondidas</div></div>
  <div class="stat"><div class="value">{avg_latency:.1f}s</div><div class="label">Latencia Media</div></div>
  <div class="stat"><div class="value">{meta.get('vector_count', 0):,}</div><div class="label">Vectors</div></div>
</div>

<h2>Por Categoria</h2>
<div class="cat-grid">"""]

    for cat_key, cat_label in cat_names.items():
        cd = cats.get(cat_key, {"scores": [], "answered": 0, "total": 0})
        cs = sum(cd["scores"]) / max(len(cd["scores"]), 1) if cd["scores"] else 0
        html_parts.append(f"""<div class="cat-card">
  <div class="name">{cat_label}</div>
  <div class="score" style="color:{score_color(cs)}">{cs:.3f}</div>
  <div class="name">{cd['answered']}/{cd['total']} respondidas</div>
</div>""")

    html_parts.append("</div><h2>Detalhe por Pergunta</h2>")

    for r in results:
        m = r.get("metrics", {})
        avg = m.get("avg_score", 0)
        cls = "high" if avg >= 0.65 else "mid" if avg >= 0.5 else "low"
        chunks = r.get("chunks", [])
        answer = r.get("answer", "")
        filters = r.get("filters_applied", {})

        filter_str = ""
        if filters:
            parts = []
            if "$and" in filters:
                for cond in filters["$and"]:
                    for k, v in cond.items():
                        if isinstance(v, dict) and "$eq" in v:
                            parts.append(f"{k}={v['$eq']}")
            else:
                for k, v in filters.items():
                    if isinstance(v, dict) and "$eq" in v:
                        parts.append(f"{k}={v['$eq']}")
            if parts:
                filter_str = f'<div class="filters">Filtros: {", ".join(parts)}</div>'

        html_parts.append(f"""<div class="question {cls}">
  <div class="q-header">
    <span class="q-id">Q{r['question_id']} | {cat_names.get(r['category'], r['category'])}</span>
    <span class="q-score" style="color:{score_color(avg)}">{avg:.3f}</span>
  </div>
  <div class="q-text">{html.escape(r['question'])}</div>
  {filter_str}""")

        if answer:
            html_parts.append(f'<div class="answer">{html.escape(answer)}</div>')

        if chunks:
            html_parts.append('<h3>Chunks Utilizados</h3>')
            for c in chunks[:5]:
                ct = "img" if c.get("content_type") == "slide_image" else "txt"
                sc = c.get("score", 0)
                fname = html.escape(c.get("file_name", "?")[:60])
                country = c.get("country", "")
                bandera = c.get("bandera", "")
                team = c.get("team", "")
                fecha = c.get("fecha", "")
                preview = html.escape(c.get("text", "")[:150])
                html_parts.append(f"""<div class="chunk">
  <span class="badge {ct}">{ct}</span>
  <span class="score-pill" style="color:{score_color(sc)}">{sc:.3f}</span>
  <div>
    <div class="file">{fname}</div>
    <div class="meta-tags">{country} | {bandera} | {team} | {fecha}</div>
    <div class="preview">{preview}...</div>
  </div>
</div>""")
        else:
            html_parts.append('<div class="no-results">Sin resultados — filtro demasiado restrictivo o sin datos para esta consulta</div>')

        met_parts = []
        if m.get("unique_files"): met_parts.append(f"<span>{m['unique_files']} archivos</span>")
        if m.get("text_chunks") is not None: met_parts.append(f"<span>{m.get('text_chunks',0)} txt / {m.get('image_chunks',0)} img</span>")
        if m.get("filter_accuracy") is not None: met_parts.append(f"<span>Filter: {m['filter_accuracy']*100:.0f}%</span>")
        if m.get("latency_total_s"): met_parts.append(f"<span>{m['latency_total_s']:.1f}s</span>")
        if met_parts:
            html_parts.append(f'<div class="metrics">{"".join(met_parts)}</div>')

        html_parts.append("</div>")

    html_parts.append("</body></html>")
    return "\n".join(html_parts)


if __name__ == "__main__":
    data = load_data()
    html_content = generate_html(data)
    out = Path(".tmp/stress_test_report.html")
    out.write_text(html_content, encoding="utf-8")
    print(f"Report generated: {out}")
