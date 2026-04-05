from __future__ import annotations

import csv
import html
import os
import re
from datetime import datetime
from typing import Any

from src.config import AppConfig, FilterConfig
from src.models import ScoredPost

CSV_FIELDS = [
    "collected_at",
    "keyword",
    "author",
    "post_snippet",
    "likes",
    "views",
    "post_url",
    "post_date",
    "category",
    "priority_score",
    "relevance_score",
    "engagement_score",
    "response_value_score",
    "freshness_score",
    "trending_score",
    "respond_recommendation",
    "response_reason",
    "suggested_response",
    "is_within_lookback",
]


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _safe_post_url(url: str) -> str:
    """
    Ensure the post URL is a working LinkedIn link.
    Broken form:  /posts/mrudski-share-1234567  (no short code)
    Fixed form:   /feed/update/urn:li:activity:1234567/
    """
    if not url:
        return url
    if "feed/update/urn" in url:
        return url
    m = re.search(r'[/-](\d{15,20})(?:[^/]*)$', url)
    if m and "/posts/" in url:
        activity_id = m.group(1)
        return f"https://www.linkedin.com/feed/update/urn:li:activity:{activity_id}/"
    return url


def _to_row(sp: ScoredPost) -> dict[str, Any]:
    return {
        "collected_at": sp.collected_at.isoformat(),
        "keyword": sp.keyword,
        "author": sp.author,
        "post_snippet": sp.post_snippet,
        "likes": sp.likes,
        "views": sp.views,
        "post_url": _safe_post_url(sp.post_url),
        "post_date": sp.post_date_str,
        "category": sp.category,
        "priority_score": sp.priority_score,
        "relevance_score": sp.relevance_score,
        "engagement_score": sp.engagement_score,
        "response_value_score": sp.response_value_score,
        "freshness_score": sp.freshness_score,
        "trending_score": sp.trending_score,
        "respond_recommendation": sp.respond_recommendation,
        "response_reason": sp.response_reason,
        "suggested_response": sp.suggested_response,
        "is_within_lookback": sp.is_within_lookback,
    }


def generate_csv(scored_posts: list[ScoredPost], output_dir: str) -> str:
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, f"linkedin_report_{_timestamp()}.csv")
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for sp in scored_posts:
            writer.writerow(_to_row(sp))
    return path


def _rec_label(rec: str) -> tuple[str, str]:
    """Return (label, color) for a recommendation value."""
    return {
        "yes":   ("Respond",  "#16a34a"),
        "maybe": ("Consider", "#d97706"),
        "no":    ("Skip",     "#dc2626"),
    }.get(rec, ("Unknown", "#94a3b8"))


def _cat_label(cat: str) -> tuple[str, str]:
    return {
        "technical": ("Technical", "#2563eb"),
        "hiring":    ("Hiring",    "#7c3aed"),
        "other":     ("Other",     "#64748b"),
    }.get(cat.lower(), (cat.title(), "#64748b"))


def _score_pill(value: float, max_val: float = 10.0, label: str = "") -> str:
    pct = min(value / max_val * 100, 100)
    color = "#16a34a" if pct >= 70 else "#d97706" if pct >= 40 else "#dc2626"
    return (
        f'<div class="score-pill">'
        f'<div class="score-pill-label">{label}</div>'
        f'<div class="score-bar-bg"><div class="score-bar-fill" style="width:{pct:.0f}%;background:{color};"></div></div>'
        f'<div class="score-pill-val">{value:.1f}</div>'
        f'</div>'
    )


def generate_html(
    scored_posts: list[ScoredPost],
    config: AppConfig,
    output_dir: str,
    run_ts: str = "",
) -> str:
    os.makedirs(output_dir, exist_ok=True)
    ts = _timestamp()
    path = os.path.join(output_dir, f"linkedin_report_{ts}.html")
    run_ts = run_ts or datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    yes_count   = sum(1 for s in scored_posts if s.respond_recommendation == "yes")
    maybe_count = sum(1 for s in scored_posts if s.respond_recommendation == "maybe")
    no_count    = sum(1 for s in scored_posts if s.respond_recommendation == "no")
    keywords_str = ", ".join(config.keywords)
    f = config.filters

    # ── Build post cards ──────────────────────────────────────────────────
    cards_html = ""
    for i, sp in enumerate(scored_posts):
        post_url    = _safe_post_url(sp.post_url)
        snippet_esc = html.escape(sp.post_snippet or "")
        response_esc = html.escape(sp.suggested_response or "")
        reason_esc  = html.escape(sp.response_reason or "")
        author_esc  = html.escape(sp.author or "Unknown")
        keyword_esc = html.escape(sp.keyword or "")
        rec_label, rec_color = _rec_label(sp.respond_recommendation)
        cat_label, cat_color = _cat_label(sp.category)
        date_str    = sp.post_date_str or "—"
        has_response = bool(sp.suggested_response and sp.suggested_response.strip())

        scores_html = (
            _score_pill(sp.relevance_score, label="Relevance") +
            _score_pill(sp.engagement_score, label="Engagement") +
            _score_pill(sp.freshness_score, label="Freshness") +
            _score_pill(sp.trending_score, label="Trending")
        )

        response_block = ""
        if has_response:
            response_block = f"""
            <div class="response-block">
              <div class="response-header">
                <span class="response-icon">💬</span>
                <span class="response-title">Suggested Response</span>
                <button class="copy-btn" onclick="copyResponse(this, 'resp_{i}')">Copy</button>
              </div>
              <div id="resp_{i}" class="response-text">{response_esc}</div>
            </div>"""

        cards_html += f"""
        <div class="post-card" data-rec="{sp.respond_recommendation}" data-cat="{sp.category}">
          <div class="card-header">
            <div class="card-header-left">
              <span class="rec-badge" style="background:{rec_color};">{rec_label}</span>
              <span class="cat-badge" style="background:{cat_color};">{cat_label}</span>
              <span class="priority-badge">Priority {sp.priority_score:.0f}</span>
            </div>
            <div class="card-header-right">
              <span class="card-date">{date_str}</span>
              <a class="view-link" href="{post_url}" target="_blank" rel="noopener">View on LinkedIn →</a>
            </div>
          </div>

          <div class="card-body">
            <div class="card-left">
              <div class="post-meta">
                <span class="author-name">{author_esc}</span>
                <span class="keyword-tag">{keyword_esc}</span>
              </div>
              <div class="post-snippet" title="{snippet_esc}">{snippet_esc}</div>
              <div class="post-stats">
                <span>👍 {sp.likes:,}</span>
                <span>👁 {sp.views:,}</span>
                <span class="reason-text">{reason_esc}</span>
              </div>
            </div>
            <div class="card-scores">
              {scores_html}
            </div>
          </div>

          {response_block}
        </div>"""

    # ── Full HTML ─────────────────────────────────────────────────────────
    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>LinkedIn Connect Intelligence — {run_ts}</title>
<style>
/* ── Reset & base ── */
*, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
       font-size: 0.9rem; color: #1e293b; background: #f1f5f9; min-height: 100vh; }}

/* ── Layout ── */
.page {{ max-width: 1100px; margin: 0 auto; padding: 28px 20px 60px; }}
h1 {{ font-size: 1.5rem; font-weight: 700; color: #0f172a; }}
.meta {{ color: #64748b; font-size: 0.8rem; margin-top: 4px; margin-bottom: 24px; }}

/* ── Summary cards ── */
.summary {{ display: flex; gap: 12px; flex-wrap: wrap; margin-bottom: 20px; }}
.stat-card {{ background: white; border: 1px solid #e2e8f0; border-radius: 10px;
             padding: 14px 20px; min-width: 120px; }}
.stat-card .val {{ font-size: 2rem; font-weight: 800; color: #0f172a; line-height: 1; }}
.stat-card .lbl {{ font-size: 0.7rem; text-transform: uppercase; letter-spacing: .05em;
                  color: #94a3b8; margin-top: 4px; }}
.stat-card.yes .val  {{ color: #16a34a; }}
.stat-card.maybe .val{{ color: #d97706; }}
.stat-card.no .val   {{ color: #dc2626; }}

/* ── Filters bar ── */
.filter-bar {{ background: white; border: 1px solid #e2e8f0; border-radius: 8px;
              padding: 10px 16px; margin-bottom: 20px; display: flex; gap: 20px;
              flex-wrap: wrap; align-items: center; font-size: 0.8rem; color: #64748b; }}
.filter-bar strong {{ color: #1e293b; }}

/* ── Controls ── */
.controls {{ display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 16px; align-items: center; }}
.filter-btn {{ padding: 6px 14px; border-radius: 20px; border: 1px solid #e2e8f0;
              background: white; font-size: 0.8rem; cursor: pointer; color: #475569;
              transition: all .15s; }}
.filter-btn:hover, .filter-btn.active {{ background: #0f172a; color: white; border-color: #0f172a; }}
.search-box {{ padding: 6px 12px; border: 1px solid #e2e8f0; border-radius: 6px;
              font-size: 0.85rem; width: 220px; color: #1e293b; background: white; }}
.search-box:focus {{ outline: none; border-color: #3b82f6; }}
.results-count {{ font-size: 0.8rem; color: #64748b; margin-left: auto; }}

/* ── Post card ── */
.post-card {{ background: white; border: 1px solid #e2e8f0; border-radius: 12px;
             margin-bottom: 14px; overflow: hidden; transition: box-shadow .15s; }}
.post-card:hover {{ box-shadow: 0 4px 16px rgba(0,0,0,.08); }}
.post-card[data-rec="yes"]   {{ border-left: 4px solid #16a34a; }}
.post-card[data-rec="maybe"] {{ border-left: 4px solid #d97706; }}
.post-card[data-rec="no"]    {{ border-left: 4px solid #dc2626; }}

/* ── Card header ── */
.card-header {{ display: flex; justify-content: space-between; align-items: center;
               padding: 10px 16px; background: #f8fafc; border-bottom: 1px solid #f1f5f9;
               flex-wrap: wrap; gap: 8px; }}
.card-header-left {{ display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }}
.card-header-right {{ display: flex; gap: 12px; align-items: center; }}
.rec-badge, .cat-badge {{ color: white; padding: 2px 10px; border-radius: 20px;
                          font-size: 0.72rem; font-weight: 600; letter-spacing: .03em; }}
.priority-badge {{ font-size: 0.75rem; color: #475569; background: #f1f5f9;
                  padding: 2px 8px; border-radius: 20px; border: 1px solid #e2e8f0; }}
.card-date {{ font-size: 0.75rem; color: #94a3b8; }}
.view-link {{ font-size: 0.8rem; font-weight: 600; color: #2563eb; text-decoration: none; }}
.view-link:hover {{ text-decoration: underline; }}

/* ── Card body ── */
.card-body {{ display: flex; gap: 16px; padding: 14px 16px; align-items: flex-start; }}
.card-left {{ flex: 1; min-width: 0; }}
.card-scores {{ display: flex; flex-direction: column; gap: 6px; min-width: 140px; }}

.post-meta {{ display: flex; gap: 10px; align-items: baseline; margin-bottom: 6px; flex-wrap: wrap; }}
.author-name {{ font-weight: 600; font-size: 0.9rem; color: #0f172a; }}
.keyword-tag {{ font-size: 0.72rem; color: #64748b; background: #f1f5f9; padding: 1px 8px;
               border-radius: 10px; border: 1px solid #e2e8f0; }}

.post-snippet {{ font-size: 0.85rem; color: #334155; line-height: 1.55;
                display: -webkit-box; -webkit-line-clamp: 4; -webkit-box-orient: vertical;
                overflow: hidden; margin-bottom: 10px; }}

.post-stats {{ display: flex; gap: 16px; font-size: 0.78rem; color: #64748b; flex-wrap: wrap; }}
.reason-text {{ font-style: italic; color: #94a3b8; }}

/* ── Score pills ── */
.score-pill {{ display: flex; align-items: center; gap: 6px; }}
.score-pill-label {{ font-size: 0.7rem; color: #94a3b8; width: 68px; text-align: right; }}
.score-bar-bg {{ flex: 1; height: 6px; background: #e2e8f0; border-radius: 3px; overflow: hidden; }}
.score-bar-fill {{ height: 100%; border-radius: 3px; }}
.score-pill-val {{ font-size: 0.75rem; font-weight: 600; color: #475569; width: 24px; }}

/* ── Response block ── */
.response-block {{ border-top: 1px solid #e2e8f0; background: #f8fafc; padding: 14px 16px; }}
.response-header {{ display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }}
.response-icon {{ font-size: 1rem; }}
.response-title {{ font-size: 0.8rem; font-weight: 600; color: #475569;
                  text-transform: uppercase; letter-spacing: .05em; }}
.copy-btn {{ margin-left: auto; padding: 3px 10px; font-size: 0.75rem; border-radius: 5px;
            border: 1px solid #cbd5e1; background: white; cursor: pointer; color: #475569; }}
.copy-btn:hover {{ background: #0f172a; color: white; border-color: #0f172a; }}
.copy-btn.copied {{ background: #16a34a; color: white; border-color: #16a34a; }}
.response-text {{ font-size: 0.88rem; line-height: 1.65; color: #1e293b;
                 white-space: pre-wrap; font-family: inherit; }}

/* ── Hidden card ── */
.post-card.hidden {{ display: none; }}

/* ── Responsive ── */
@media (max-width: 700px) {{
  .card-body {{ flex-direction: column; }}
  .card-scores {{ flex-direction: row; flex-wrap: wrap; min-width: unset; }}
  .card-header {{ flex-direction: column; align-items: flex-start; }}
}}
</style>
</head>
<body>
<div class="page">

<h1>LinkedIn Connect Intelligence</h1>
<div class="meta">Generated {run_ts} &nbsp;·&nbsp; Keywords: <strong>{html.escape(keywords_str)}</strong></div>

<div class="summary">
  <div class="stat-card">
    <div class="val">{len(scored_posts)}</div>
    <div class="lbl">Posts scored</div>
  </div>
  <div class="stat-card yes">
    <div class="val">{yes_count}</div>
    <div class="lbl">Respond</div>
  </div>
  <div class="stat-card maybe">
    <div class="val">{maybe_count}</div>
    <div class="lbl">Consider</div>
  </div>
  <div class="stat-card no">
    <div class="val">{no_count}</div>
    <div class="lbl">Skip</div>
  </div>
</div>

<div class="filter-bar">
  <span>Min likes: <strong>{f.min_likes}</strong></span>
  <span>Min views: <strong>{f.min_views}</strong></span>
  <span>Lookback: <strong>{f.lookback_days} days</strong></span>
</div>

<div class="controls">
  <button class="filter-btn active" onclick="filterRec('all', this)">All</button>
  <button class="filter-btn" onclick="filterRec('yes', this)">Respond</button>
  <button class="filter-btn" onclick="filterRec('maybe', this)">Consider</button>
  <button class="filter-btn" onclick="filterRec('no', this)">Skip</button>
  <input class="search-box" type="text" placeholder="Search author or text…" oninput="filterSearch(this.value)">
  <span class="results-count" id="results-count">{len(scored_posts)} posts</span>
</div>

<div id="cards">
{cards_html}
</div>

</div><!-- /page -->

<script>
var activeRec = 'all';
var activeSearch = '';

function filterRec(rec, btn) {{
  activeRec = rec;
  document.querySelectorAll('.filter-btn').forEach(function(b) {{ b.classList.remove('active'); }});
  btn.classList.add('active');
  applyFilters();
}}

function filterSearch(val) {{
  activeSearch = val.toLowerCase();
  applyFilters();
}}

function applyFilters() {{
  var cards = document.querySelectorAll('.post-card');
  var visible = 0;
  cards.forEach(function(card) {{
    var recMatch = activeRec === 'all' || card.dataset.rec === activeRec;
    var searchMatch = !activeSearch ||
      card.textContent.toLowerCase().includes(activeSearch);
    if (recMatch && searchMatch) {{
      card.classList.remove('hidden');
      visible++;
    }} else {{
      card.classList.add('hidden');
    }}
  }});
  document.getElementById('results-count').textContent = visible + ' posts';
}}

function copyResponse(btn, id) {{
  var text = document.getElementById(id).textContent;
  navigator.clipboard.writeText(text).then(function() {{
    btn.textContent = 'Copied!';
    btn.classList.add('copied');
    setTimeout(function() {{
      btn.textContent = 'Copy';
      btn.classList.remove('copied');
    }}, 2000);
  }});
}}
</script>
</body>
</html>"""

    with open(path, "w", encoding="utf-8") as out:
        out.write(html_content)

    return path
