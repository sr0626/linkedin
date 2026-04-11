from __future__ import annotations

import html
import os
import re
from datetime import datetime

from src.config import AppConfig
from src.models import ScoredPost


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _safe_post_url(url: str) -> str:
    if not url:
        return url
    if "feed/update/urn" in url:
        return url
    m = re.search(r'[/-](\d{15,20})(?:[^/]*)$', url)
    if m and "/posts/" in url:
        return f"https://www.linkedin.com/feed/update/urn:li:activity:{m.group(1)}/"
    if re.search(r'linkedin\.com/in/[^/?#]+/?$', url):
        return url.rstrip('/') + '/recent-activity/all/'
    return url


def _is_profile_url(url: str) -> bool:
    if not url:
        return False
    clean = url.rstrip('/')
    if 'feed/update/urn' in clean or '/posts/' in clean:
        return False
    return bool(re.search(r'linkedin\.com/in/[^/?#]+$', clean.replace('/recent-activity/all', '')))


def _format_post_date(sp: ScoredPost) -> str:
    if sp.post.post_date:
        return sp.post.post_date.strftime("%d %b %Y, %H:%M")
    return sp.post.raw_date_str or ""


def _rec_config(rec: str) -> tuple[str, str, str, str]:
    """Return (label, border_color, bg_color, text_color)."""
    return {
        "yes":   ("Respond",  "#059669", "#ECFDF5", "#065F46"),
        "maybe": ("Consider", "#D97706", "#FFFBEB", "#92400E"),
        "no":    ("Skip",     "#DC2626", "#FEF2F2", "#991B1B"),
    }.get(rec, ("Unknown", "#94A3B8", "#F8FAFC", "#475569"))


def _cat_badge(cat: str) -> tuple[str, str, str]:
    """Return (label, bg, text)."""
    return {
        "technical": ("Technical", "#EFF6FF", "#1D4ED8"),
        "hiring":    ("Hiring",    "#F5F3FF", "#6D28D9"),
        "other":     ("Other",     "#F1F5F9", "#475569"),
    }.get(cat.lower(), (cat.title(), "#F1F5F9", "#475569"))


# ── Local HTML report ──────────────────────────────────────────────────────────

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
    f = config.filters

    cards_html = ""
    for i, sp in enumerate(scored_posts):
        post_url    = _safe_post_url(sp.post_url)
        author_esc  = html.escape(sp.author or "Unknown")
        snippet_esc = html.escape(sp.post_snippet or "")
        resp_esc    = html.escape(sp.suggested_response or "")
        resp2_esc   = html.escape(sp.suggested_response_2 or "")
        reason_esc  = html.escape(sp.response_reason or "")
        kw_esc      = html.escape(sp.keyword or "")
        post_date   = _format_post_date(sp)
        is_profile  = _is_profile_url(post_url)

        rec_label, border_col, header_bg, header_txt = _rec_config(sp.respond_recommendation)
        cat_label, cat_bg, cat_txt = _cat_badge(sp.category)

        link_label = "View Activity ↗" if is_profile else "Open Post ↗"
        link_cls   = "btn-link btn-link--profile" if is_profile else "btn-link"
        date_html  = f'<span class="meta-date">{html.escape(post_date)}</span>' if post_date else ''
        views_html = f'<span class="stat-item"><span class="stat-icon">👁</span>{sp.views:,}</span>' if sp.views else ''

        def bar(pct: float, color: str) -> str:
            p = min(int(pct), 100)
            return (
                f'<div class="score-track">'
                f'<div class="score-fill" style="width:{p}%;background:{color};"></div>'
                f'</div>'
            )

        def score_color(v: float) -> str:
            return "#059669" if v >= 7 else "#D97706" if v >= 4 else "#DC2626"

        has_response = bool(resp_esc.strip())
        response_block = ""
        if has_response:
            resp2_block = ""
            if resp2_esc.strip():
                resp2_block = f"""
            <div class="response-divider"></div>
            <div class="response-header">
              <span class="response-label">Option 2</span>
              <div class="response-actions">
                <button class="btn-action" onclick="copyResp(this,'rt{i}b')">Copy</button>
              </div>
            </div>
            <div id="rt{i}b" class="response-body">{resp2_esc}</div>"""
            response_block = f"""
          <div class="response-panel">
            <div class="response-header">
              <span class="response-label">Option 1</span>
              <div class="response-actions">
                <button class="btn-action" onclick="copyResp(this,'rt{i}')">Copy</button>
                <button class="btn-action btn-respond" id="rb{i}" onclick="markResponded({i})">Mark Responded</button>
              </div>
            </div>
            <div id="rt{i}" class="response-body">{resp_esc}</div>{resp2_block}
          </div>"""

        cards_html += f"""
        <div class="card" id="card{i}"
             data-rec="{sp.respond_recommendation}"
             data-cat="{sp.category}"
             data-url="{html.escape(post_url)}"
             data-search="{html.escape((sp.author + ' ' + (sp.post_snippet or '')).lower())}">

          <div class="card-header" style="border-left:4px solid {border_col};background:{header_bg};">
            <div class="card-header-left">
              <span class="badge-rec" style="background:{border_col};color:white;">{rec_label}</span>
              <span class="badge-cat" style="background:{cat_bg};color:{cat_txt};">{cat_label}</span>
              <span class="badge-priority">Priority <strong>{sp.priority_score:.0f}</strong>/100</span>
            </div>
            <div class="card-header-right">
              {date_html}
              <span class="responded-stamp" id="rs{i}">✓ Responded</span>
              <a class="{link_cls}" href="{post_url}" target="_blank" rel="noopener">{link_label}</a>
            </div>
          </div>

          <div class="card-body">
            <div class="card-content">
              <div class="author-row">
                <span class="author-name">{author_esc}</span>
                <span class="kw-tag">{kw_esc}</span>
              </div>
              <p class="snippet">{snippet_esc}</p>
              <div class="meta-row">
                <span class="stat-item"><span class="stat-icon">👍</span>{sp.likes:,}</span>
                {views_html}
                <span class="reason-text">{reason_esc}</span>
              </div>
            </div>

            <div class="card-scores">
              <div class="score-row">
                <span class="score-label">Relevance</span>
                {bar(sp.relevance_score * 10, score_color(sp.relevance_score))}
                <span class="score-val" style="color:{score_color(sp.relevance_score)};">{sp.relevance_score:.1f}</span>
              </div>
              <div class="score-row">
                <span class="score-label">Engagement</span>
                {bar(sp.engagement_score * 10, score_color(sp.engagement_score))}
                <span class="score-val" style="color:{score_color(sp.engagement_score)};">{sp.engagement_score:.1f}</span>
              </div>
              <div class="score-row">
                <span class="score-label">Freshness</span>
                {bar(sp.freshness_score * 10, score_color(sp.freshness_score))}
                <span class="score-val" style="color:{score_color(sp.freshness_score)};">{sp.freshness_score:.1f}</span>
              </div>
              <div class="score-row">
                <span class="score-label">Trending</span>
                {bar(sp.trending_score * 10, score_color(sp.trending_score))}
                <span class="score-val" style="color:{score_color(sp.trending_score)};">{sp.trending_score:.1f}</span>
              </div>
              <div class="priority-score" style="color:{border_col};">{sp.priority_score:.0f}<span class="priority-denom">/100</span></div>
            </div>
          </div>

          {response_block}
        </div>"""

    html_out = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Amazon Connect Intelligence</title>
<style>
/* ── Base ── */
*, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Inter', Roboto, sans-serif;
  font-size: 13px;
  color: #1E293B;
  background: #F0F4F8;
  min-height: 100vh;
  -webkit-font-smoothing: antialiased;
}}

/* ── Topbar ── */
.topbar {{
  background: #0F1E35;
  color: white;
  padding: 0 28px;
  height: 56px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  position: sticky;
  top: 0;
  z-index: 100;
  box-shadow: 0 1px 3px rgba(0,0,0,.3);
}}
.topbar-brand {{
  display: flex;
  align-items: center;
  gap: 10px;
}}
.topbar-logo {{
  width: 28px;
  height: 28px;
  background: #FF9900;
  border-radius: 6px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  font-weight: 800;
  color: #0F1E35;
}}
.topbar-title {{
  font-size: 15px;
  font-weight: 700;
  letter-spacing: .01em;
}}
.topbar-sub {{
  font-size: 11px;
  color: #94A3B8;
  margin-top: 1px;
}}
.topbar-meta {{
  font-size: 11px;
  color: #64748B;
  text-align: right;
}}

/* ── Page ── */
.page {{ max-width: 1120px; margin: 0 auto; padding: 24px 20px 64px; }}

/* ── Stats strip ── */
.stats-strip {{
  display: flex;
  gap: 12px;
  margin-bottom: 20px;
  flex-wrap: wrap;
}}
.stat-card {{
  background: white;
  border: 1px solid #E2E8F0;
  border-radius: 10px;
  padding: 14px 22px;
  min-width: 110px;
  text-align: center;
  box-shadow: 0 1px 2px rgba(0,0,0,.04);
}}
.stat-card .num {{
  font-size: 2rem;
  font-weight: 800;
  line-height: 1;
  letter-spacing: -.02em;
}}
.stat-card .lbl {{
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: .08em;
  color: #94A3B8;
  margin-top: 4px;
  font-weight: 600;
}}
.stat-card.s-total  .num {{ color: #1E293B; }}
.stat-card.s-yes    .num {{ color: #059669; }}
.stat-card.s-maybe  .num {{ color: #D97706; }}
.stat-card.s-no     .num {{ color: #DC2626; }}
.stat-card.s-resp   .num {{ color: #6366F1; }}

/* ── Filter meta strip ── */
.filter-meta {{
  display: flex;
  gap: 16px;
  font-size: 11px;
  color: #64748B;
  background: white;
  border: 1px solid #E2E8F0;
  border-radius: 8px;
  padding: 8px 16px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}}
.filter-meta strong {{ color: #1E293B; }}

/* ── Toolbar ── */
.toolbar {{
  display: flex;
  gap: 6px;
  align-items: center;
  flex-wrap: wrap;
  margin-bottom: 16px;
  background: white;
  border: 1px solid #E2E8F0;
  border-radius: 10px;
  padding: 10px 14px;
  box-shadow: 0 1px 2px rgba(0,0,0,.04);
}}
.filter-btn {{
  padding: 5px 14px;
  border-radius: 6px;
  border: 1px solid #E2E8F0;
  background: #F8FAFC;
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  color: #475569;
  transition: all .12s;
}}
.filter-btn:hover {{ background: #EFF6FF; color: #2563EB; border-color: #BFDBFE; }}
.filter-btn.active {{ background: #1E3A5F; color: white; border-color: #1E3A5F; }}
.divider {{ width: 1px; height: 20px; background: #E2E8F0; margin: 0 4px; }}
.search-box {{
  padding: 5px 12px;
  border: 1px solid #E2E8F0;
  border-radius: 6px;
  font-size: 12px;
  width: 220px;
  color: #1E293B;
  background: #F8FAFC;
  transition: border-color .12s;
}}
.search-box:focus {{ outline: none; border-color: #2563EB; background: white; }}
.post-count {{ font-size: 12px; color: #94A3B8; margin-left: auto; font-weight: 500; }}

/* ── Card ── */
.card {{
  background: white;
  border: 1px solid #E2E8F0;
  border-radius: 12px;
  margin-bottom: 10px;
  overflow: hidden;
  box-shadow: 0 1px 3px rgba(0,0,0,.04);
  transition: box-shadow .15s, transform .15s;
}}
.card:hover {{ box-shadow: 0 4px 16px rgba(0,0,0,.08); transform: translateY(-1px); }}
.card.hidden {{ display: none; }}
.card.responded {{ opacity: .5; }}

/* ── Card header ── */
.card-header {{
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 9px 16px;
  border-bottom: 1px solid rgba(0,0,0,.05);
  flex-wrap: wrap;
  gap: 8px;
}}
.card-header-left {{ display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }}
.card-header-right {{ display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }}

.badge-rec {{
  padding: 3px 10px;
  border-radius: 5px;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: .03em;
  text-transform: uppercase;
}}
.badge-cat {{
  padding: 3px 10px;
  border-radius: 5px;
  font-size: 11px;
  font-weight: 600;
}}
.badge-priority {{
  font-size: 11px;
  color: #64748B;
  background: #F1F5F9;
  padding: 3px 10px;
  border-radius: 5px;
  border: 1px solid #E2E8F0;
}}
.badge-priority strong {{ color: #1E293B; }}

.meta-date {{ font-size: 11px; color: #94A3B8; }}
.responded-stamp {{
  display: none;
  font-size: 11px;
  font-weight: 700;
  color: #059669;
  background: #ECFDF5;
  padding: 3px 10px;
  border-radius: 5px;
  border: 1px solid #A7F3D0;
}}
.btn-link {{
  font-size: 11px;
  font-weight: 700;
  color: #2563EB;
  text-decoration: none;
  padding: 4px 12px;
  border: 1px solid #BFDBFE;
  border-radius: 6px;
  background: #EFF6FF;
  transition: all .12s;
  white-space: nowrap;
}}
.btn-link:hover {{ background: #2563EB; color: white; border-color: #2563EB; }}
.btn-link--profile {{ color: #7C3AED; border-color: #DDD6FE; background: #FAF5FF; }}
.btn-link--profile:hover {{ background: #7C3AED; color: white; border-color: #7C3AED; }}

/* ── Card body ── */
.card-body {{
  display: flex;
  gap: 16px;
  padding: 14px 16px;
  align-items: flex-start;
}}
.card-content {{ flex: 1; min-width: 0; }}

.author-row {{
  display: flex;
  align-items: baseline;
  gap: 8px;
  margin-bottom: 7px;
  flex-wrap: wrap;
}}
.author-name {{
  font-size: 14px;
  font-weight: 700;
  color: #0F172A;
}}
.kw-tag {{
  font-size: 10px;
  color: #64748B;
  background: #F1F5F9;
  border: 1px solid #E2E8F0;
  padding: 2px 8px;
  border-radius: 4px;
  font-weight: 500;
}}
.snippet {{
  font-size: 13px;
  line-height: 1.65;
  color: #334155;
  display: -webkit-box;
  -webkit-line-clamp: 4;
  -webkit-box-orient: vertical;
  overflow: hidden;
  margin-bottom: 10px;
}}
.meta-row {{
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  font-size: 12px;
  color: #64748B;
}}
.stat-item {{ display: flex; align-items: center; gap: 4px; font-weight: 500; }}
.stat-icon {{ font-size: 12px; }}
.reason-text {{ font-style: italic; color: #94A3B8; font-size: 11px; }}

/* ── Scores column ── */
.card-scores {{
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 160px;
  padding-left: 16px;
  border-left: 1px solid #F1F5F9;
}}
.score-row {{
  display: flex;
  align-items: center;
  gap: 6px;
}}
.score-label {{
  font-size: 10px;
  color: #94A3B8;
  width: 65px;
  text-align: right;
  font-weight: 500;
  text-transform: uppercase;
  letter-spacing: .04em;
  flex-shrink: 0;
}}
.score-track {{
  flex: 1;
  height: 5px;
  background: #F1F5F9;
  border-radius: 99px;
  overflow: hidden;
}}
.score-fill {{
  height: 100%;
  border-radius: 99px;
  transition: width .3s ease;
}}
.score-val {{
  font-size: 11px;
  font-weight: 700;
  width: 26px;
  text-align: right;
  flex-shrink: 0;
}}
.priority-score {{
  font-size: 2rem;
  font-weight: 800;
  text-align: right;
  line-height: 1;
  margin-top: 6px;
  letter-spacing: -.02em;
}}
.priority-denom {{
  font-size: 11px;
  font-weight: 400;
  color: #94A3B8;
}}

/* ── Response panel ── */
.response-panel {{
  border-top: 1px solid #F1F5F9;
  background: #FAFBFD;
  padding: 12px 16px;
}}
.response-divider {{
  border: none;
  border-top: 1px dashed #E2E8F0;
  margin: 12px 0;
}}
.response-header {{
  display: flex;
  align-items: center;
  margin-bottom: 8px;
}}
.response-label {{
  font-size: 10px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: .08em;
  color: #94A3B8;
}}
.response-actions {{ margin-left: auto; display: flex; gap: 6px; }}
.btn-action {{
  padding: 4px 12px;
  font-size: 11px;
  font-weight: 600;
  border-radius: 6px;
  border: 1px solid #E2E8F0;
  background: white;
  cursor: pointer;
  color: #475569;
  transition: all .12s;
}}
.btn-action:hover {{ background: #0F1E35; color: white; border-color: #0F1E35; }}
.btn-respond {{ color: #059669; border-color: #A7F3D0; }}
.btn-respond:hover,.btn-respond.done {{ background: #059669; color: white; border-color: #059669; }}
.response-body {{
  font-size: 13px;
  line-height: 1.75;
  color: #1E293B;
  white-space: pre-wrap;
  font-family: inherit;
}}

/* ── Responsive ── */
@media(max-width:720px) {{
  .card-body {{ flex-direction: column; }}
  .card-scores {{ border-left: none; border-top: 1px solid #F1F5F9; padding-left: 0; padding-top: 12px; flex-direction: row; flex-wrap: wrap; min-width: unset; }}
}}
</style>
</head>
<body>

<div class="topbar">
  <div class="topbar-brand">
    <div class="topbar-logo">AC</div>
    <div>
      <div class="topbar-title">Amazon Connect Intelligence</div>
      <div class="topbar-sub">LinkedIn Post Monitor</div>
    </div>
  </div>
  <div class="topbar-meta">
    Generated {html.escape(run_ts)}<br>
    {len(scored_posts)} posts scored
  </div>
</div>

<div class="page">

  <div class="stats-strip">
    <div class="stat-card s-total"><div class="num">{len(scored_posts)}</div><div class="lbl">Total</div></div>
    <div class="stat-card s-yes"><div class="num">{yes_count}</div><div class="lbl">Respond</div></div>
    <div class="stat-card s-maybe"><div class="num">{maybe_count}</div><div class="lbl">Consider</div></div>
    <div class="stat-card s-no"><div class="num">{no_count}</div><div class="lbl">Skip</div></div>
    <div class="stat-card s-resp"><div class="num" id="responded-count">0</div><div class="lbl">Responded</div></div>
  </div>

  <div class="filter-meta">
    <span>Min likes: <strong>{f.min_likes}</strong></span>
    <span>Min views: <strong>{f.min_views}</strong></span>
    <span>Lookback: <strong>{f.lookback_days} days</strong></span>
    <span>Keywords: <strong>{html.escape(', '.join(config.keywords))}</strong></span>
  </div>

  <div class="toolbar">
    <button class="filter-btn active" onclick="setRec('all',this)">All</button>
    <button class="filter-btn" onclick="setRec('yes',this)">Respond</button>
    <button class="filter-btn" onclick="setRec('maybe',this)">Consider</button>
    <button class="filter-btn" onclick="setRec('no',this)">Skip</button>
    <div class="divider"></div>
    <button class="filter-btn" onclick="setRec('responded',this)">Responded</button>
    <button class="filter-btn" onclick="setRec('pending',this)">Not Responded</button>
    <div class="divider"></div>
    <input class="search-box" type="text" placeholder="&#128269; Search author or text…" oninput="doSearch(this.value)">
    <span class="post-count" id="cnt">{len(scored_posts)} posts</span>
  </div>

  <div id="cards">
{cards_html}
  </div>

</div>

<script>
var STORE_KEY = 'li_connect_responded';
var responded = JSON.parse(localStorage.getItem(STORE_KEY) || '{{}}');
var recFilter = 'all';
var searchVal = '';

document.querySelectorAll('.card[data-url]').forEach(function(card) {{
  var url = card.getAttribute('data-url');
  if (url && responded[url]) setRespondedUI(card.id.replace('card',''), true);
}});
updateRespondedCount();

function markResponded(i) {{
  var card = document.getElementById('card' + i);
  if (!card) return;
  var url = card.getAttribute('data-url');
  var isNow = !responded[url];
  responded[url] = isNow;
  localStorage.setItem(STORE_KEY, JSON.stringify(responded));
  setRespondedUI(i, isNow);
  updateRespondedCount();
  applyFilters();
}}

function setRespondedUI(i, on) {{
  var card  = document.getElementById('card' + i);
  var stamp = document.getElementById('rs' + i);
  var btn   = document.getElementById('rb' + i);
  if (!card) return;
  card.classList.toggle('responded', on);
  if (stamp) stamp.style.display = on ? 'inline-block' : 'none';
  if (btn) {{ btn.textContent = on ? 'Undo' : 'Mark Responded'; btn.classList.toggle('done', on); }}
}}

function updateRespondedCount() {{
  var n = 0;
  document.querySelectorAll('.card[data-url]').forEach(function(c) {{
    if (responded[c.getAttribute('data-url')]) n++;
  }});
  var el = document.getElementById('responded-count');
  if (el) el.textContent = n;
}}

function setRec(r, btn) {{
  recFilter = r;
  document.querySelectorAll('.filter-btn').forEach(function(b) {{ b.classList.remove('active'); }});
  btn.classList.add('active');
  applyFilters();
}}

function doSearch(v) {{ searchVal = v.toLowerCase(); applyFilters(); }}

function applyFilters() {{
  var cards = document.querySelectorAll('.card');
  var n = 0;
  cards.forEach(function(card) {{
    var url = card.getAttribute('data-url');
    var isResp = responded[url];
    var recOk = recFilter === 'all'
      || (recFilter === 'responded' && isResp)
      || (recFilter === 'pending'   && !isResp)
      || card.dataset.rec === recFilter;
    var srchOk = !searchVal || card.dataset.search.includes(searchVal);
    var show = recOk && srchOk;
    card.classList.toggle('hidden', !show);
    if (show) n++;
  }});
  document.getElementById('cnt').textContent = n + ' posts';
}}

function copyResp(btn, id) {{
  var text = document.getElementById(id).textContent;
  navigator.clipboard.writeText(text).then(function() {{
    var orig = btn.textContent;
    btn.textContent = 'Copied!';
    btn.style.background = '#059669';
    btn.style.color = 'white';
    setTimeout(function() {{ btn.textContent = orig; btn.style.background = ''; btn.style.color = ''; }}, 2000);
  }});
}}
</script>
</body>
</html>"""

    with open(path, "w", encoding="utf-8") as out:
        out.write(html_out)
    return path


# ── Email-safe HTML report ─────────────────────────────────────────────────────

def generate_email_html(
    scored_posts: list[ScoredPost],
    config: AppConfig,
    run_ts: str = "",
) -> str:
    """Email-safe HTML — inline styles only, no JS, renders in Gmail/Outlook."""
    run_ts = run_ts or datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    email_posts = [sp for sp in scored_posts if sp.respond_recommendation in ("yes", "maybe")]
    yes_count   = sum(1 for s in scored_posts if s.respond_recommendation == "yes")
    maybe_count = sum(1 for s in scored_posts if s.respond_recommendation == "maybe")
    no_count    = sum(1 for s in scored_posts if s.respond_recommendation == "no")
    total       = len(scored_posts)

    REC = {
        "yes":   ("Respond",  "#059669", "#ECFDF5", "#065F46"),
        "maybe": ("Consider", "#D97706", "#FFFBEB", "#92400E"),
    }

    def score_bar(label: str, value: float) -> str:
        pct = min(int(value * 10), 100)
        col = "#059669" if value >= 7 else "#D97706" if value >= 4 else "#DC2626"
        return (
            f'<tr>'
            f'<td style="font-size:10px;color:#94A3B8;width:68px;text-align:right;'
            f'padding-right:6px;font-weight:600;text-transform:uppercase;letter-spacing:.04em;'
            f'padding-bottom:4px;">{label}</td>'
            f'<td style="padding-bottom:4px;">'
            f'<div style="background:#F1F5F9;border-radius:99px;height:5px;width:80px;overflow:hidden;">'
            f'<div style="background:{col};width:{pct}%;height:5px;border-radius:99px;"></div>'
            f'</div></td>'
            f'<td style="font-size:11px;font-weight:700;color:{col};padding-left:5px;'
            f'padding-bottom:4px;width:28px;">{value:.1f}</td>'
            f'</tr>'
        )

    def stat_cell(num: str, label: str, color: str) -> str:
        return (
            f'<td style="padding:4px;">'
            f'<div style="background:white;border:1px solid #E2E8F0;border-radius:10px;'
            f'padding:14px 20px;text-align:center;min-width:90px;">'
            f'<div style="font-size:28px;font-weight:800;color:{color};line-height:1;'
            f'letter-spacing:-.02em;">{num}</div>'
            f'<div style="font-size:10px;text-transform:uppercase;letter-spacing:.08em;'
            f'color:#94A3B8;margin-top:4px;font-weight:600;">{label}</div>'
            f'</div></td>'
        )

    cards_html = ""
    for sp in email_posts:
        post_url   = _safe_post_url(sp.post_url)
        author_esc = html.escape(sp.author or "Unknown")
        snip_esc   = html.escape(sp.post_snippet or "")
        resp_esc   = html.escape(sp.suggested_response or "")
        resp2_esc  = html.escape(sp.suggested_response_2 or "")
        reason_esc = html.escape(sp.response_reason or "")
        kw_esc     = html.escape(sp.keyword or "")
        post_date  = _format_post_date(sp)
        is_profile = _is_profile_url(post_url)

        rec_label, border_col, header_bg, header_txt = REC.get(
            sp.respond_recommendation, ("Unknown", "#94A3B8", "#F8FAFC", "#475569")
        )
        cat_label, cat_bg, cat_txt = _cat_badge(sp.category)
        link_label = "View Activity →" if is_profile else "Open Post →"
        link_color = "#7C3AED" if is_profile else "#2563EB"

        scores = (
            score_bar("Relevance",  sp.relevance_score) +
            score_bar("Engagement", sp.engagement_score) +
            score_bar("Freshness",  sp.freshness_score) +
            score_bar("Trending",   sp.trending_score)
        )

        resp_block = ""
        if resp_esc.strip():
            resp2_section = ""
            if resp2_esc.strip():
                resp2_section = f"""
                <div style="border-top:1px dashed #E2E8F0;margin:10px 0;"></div>
                <div style="font-size:10px;font-weight:700;text-transform:uppercase;
                     letter-spacing:.08em;color:#94A3B8;margin-bottom:8px;">Option 2</div>
                <div style="font-size:13px;line-height:1.75;color:#1E293B;
                     white-space:pre-wrap;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Arial,sans-serif;">{resp2_esc}</div>"""
            resp_block = f"""
            <tr><td colspan="2" style="padding:0;">
              <div style="background:#FAFBFD;border-top:1px solid #E2E8F0;padding:12px 16px;">
                <div style="font-size:10px;font-weight:700;text-transform:uppercase;
                     letter-spacing:.08em;color:#94A3B8;margin-bottom:8px;">Option 1</div>
                <div style="font-size:13px;line-height:1.75;color:#1E293B;
                     white-space:pre-wrap;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Arial,sans-serif;">{resp_esc}</div>{resp2_section}
              </div>
            </td></tr>"""

        date_html = f'<span style="font-size:11px;color:#94A3B8;margin-right:12px;">&#128197; {html.escape(post_date)}</span>' if post_date else ''
        views_html = f'&nbsp;&nbsp;&#128065; {sp.views:,}' if sp.views else ''
        score_col = "#059669" if sp.priority_score >= 70 else "#D97706" if sp.priority_score >= 45 else "#DC2626"

        cards_html += f"""
        <table width="100%" cellpadding="0" cellspacing="0" border="0"
               style="margin-bottom:12px;background:white;border:1px solid #E2E8F0;
                      border-radius:12px;border-left:4px solid {border_col};overflow:hidden;
                      font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Arial,sans-serif;
                      box-shadow:0 1px 3px rgba(0,0,0,.04);">
          <tr style="background:{header_bg};">
            <td style="padding:9px 16px;vertical-align:middle;">
              <span style="display:inline-block;padding:3px 10px;border-radius:5px;font-size:10px;
                    font-weight:700;text-transform:uppercase;letter-spacing:.03em;
                    background:{border_col};color:white;margin-right:6px;">{rec_label}</span>
              <span style="display:inline-block;padding:3px 10px;border-radius:5px;font-size:10px;
                    font-weight:600;background:{cat_bg};color:{cat_txt};margin-right:6px;">{cat_label}</span>
              <span style="font-size:11px;color:#64748B;background:#F1F5F9;padding:3px 10px;
                    border-radius:5px;border:1px solid #E2E8F0;">Priority <strong style="color:#1E293B;">{sp.priority_score:.0f}</strong>/100</span>
            </td>
            <td style="padding:9px 16px;text-align:right;vertical-align:middle;white-space:nowrap;">
              {date_html}
              <a href="{html.escape(post_url)}" style="font-size:11px;font-weight:700;
                 color:{link_color};text-decoration:none;">{link_label}</a>
            </td>
          </tr>
          <tr>
            <td style="padding:14px 16px;vertical-align:top;">
              <div style="font-size:14px;font-weight:700;color:#0F172A;margin-bottom:6px;">
                {author_esc}
                <span style="font-size:10px;font-weight:500;color:#64748B;background:#F1F5F9;
                      border:1px solid #E2E8F0;padding:2px 8px;border-radius:4px;
                      margin-left:8px;">{kw_esc}</span>
              </div>
              <div style="font-size:13px;color:#334155;line-height:1.65;margin-bottom:10px;">
                {snip_esc}
              </div>
              <div style="font-size:12px;color:#64748B;">
                &#128077; {sp.likes:,}{views_html}
                &nbsp;&nbsp;<em style="color:#94A3B8;font-size:11px;">{reason_esc}</em>
              </div>
            </td>
            <td style="padding:14px 16px;vertical-align:top;width:175px;
                       border-left:1px solid #F1F5F9;">
              <table cellpadding="0" cellspacing="0" border="0">{scores}</table>
              <div style="font-size:2rem;font-weight:800;color:{score_col};
                   text-align:right;margin-top:8px;line-height:1;letter-spacing:-.02em;">
                {sp.priority_score:.0f}<span style="font-size:11px;font-weight:400;color:#94A3B8;">/100</span>
              </div>
            </td>
          </tr>
          {resp_block}
        </table>"""

    f = config.filters
    kw_str = html.escape(", ".join(config.keywords))

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Amazon Connect Intelligence · {html.escape(run_ts)}</title>
</head>
<body style="margin:0;padding:0;background:#F0F4F8;
     font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Arial,sans-serif;">

<table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#F0F4F8;">
<tr><td align="center" style="padding:24px 16px;">
<table width="660" cellpadding="0" cellspacing="0" border="0" style="max-width:660px;width:100%;">

  <!-- Header -->
  <tr>
    <td style="background:#0F1E35;border-radius:12px 12px 0 0;padding:20px 24px;">
      <table cellpadding="0" cellspacing="0" border="0" width="100%">
        <tr>
          <td>
            <div style="display:inline-block;background:#FF9900;border-radius:8px;
                 width:34px;height:34px;text-align:center;line-height:34px;
                 font-size:16px;font-weight:800;color:#0F1E35;margin-bottom:8px;">AC</div>
            <div style="font-size:17px;font-weight:700;color:white;letter-spacing:.01em;">
              Amazon Connect Intelligence</div>
            <div style="font-size:11px;color:#64748B;margin-top:3px;">
              {html.escape(run_ts)} &nbsp;·&nbsp; {kw_str}
            </div>
          </td>
        </tr>
      </table>
    </td>
  </tr>

  <!-- Stats -->
  <tr>
    <td style="background:#F0F4F8;padding:16px 0 8px;">
      <table cellpadding="0" cellspacing="0" border="0">
        <tr>
          {stat_cell(str(total),       "Total",    "#1E293B")}
          {stat_cell(str(yes_count),   "Respond",  "#059669")}
          {stat_cell(str(maybe_count), "Consider", "#D97706")}
          {stat_cell(str(no_count),    "Skip",     "#DC2626")}
          {stat_cell("—",              "Responded","#6366F1")}
        </tr>
      </table>
    </td>
  </tr>

  <!-- Filter meta -->
  <tr>
    <td style="padding:0 0 12px;">
      <div style="font-size:11px;color:#94A3B8;">
        Min likes: <strong style="color:#475569;">{f.min_likes}</strong>
        &nbsp;·&nbsp; Min views: <strong style="color:#475569;">{f.min_views}</strong>
        &nbsp;·&nbsp; Lookback: <strong style="color:#475569;">{f.lookback_days} days</strong>
        &nbsp;·&nbsp; Showing <strong style="color:#475569;">{len(email_posts)}</strong> actionable posts
      </div>
    </td>
  </tr>

  <!-- Cards -->
  <tr>
    <td>
      {cards_html}
    </td>
  </tr>

  <!-- Footer -->
  <tr>
    <td style="padding:16px 0;text-align:center;font-size:11px;color:#94A3B8;">
      Amazon Connect Intelligence &nbsp;·&nbsp; LinkedIn Post Monitor
    </td>
  </tr>

</table>
</td></tr>
</table>
</body>
</html>"""


def _stat_cell(number: str, label: str, color: str) -> str:
    return (
        f'<td style="background:white;border:1px solid #e2e8f0;border-radius:10px;'
        f'padding:12px 20px;text-align:center;min-width:90px;">'
        f'<div style="font-size:28px;font-weight:800;color:{color};line-height:1;">'
        f'{number}</div>'
        f'<div style="font-size:10px;text-transform:uppercase;letter-spacing:.06em;'
        f'color:#94a3b8;margin-top:3px;">{label}</div>'
        f'</td>'
    )
