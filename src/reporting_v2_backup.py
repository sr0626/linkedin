from __future__ import annotations

import html
import os
import re
from datetime import datetime
from typing import Any

from src.config import AppConfig, FilterConfig
from src.models import ScoredPost


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _safe_post_url(url: str) -> str:
    """
    Ensure the post URL is a working LinkedIn link.
    Broken form:  /posts/mrudski-share-1234567     → fix to /feed/update/urn:...
    Profile URL:  /in/slug/                         → send to recent-activity page
    Already good: /feed/update/urn:li:activity:...  → leave as-is
    """
    if not url:
        return url
    if "feed/update/urn" in url:
        return url
    # Fix broken /posts/ URL missing short code
    m = re.search(r'[/-](\d{15,20})(?:[^/]*)$', url)
    if m and "/posts/" in url:
        activity_id = m.group(1)
        return f"https://www.linkedin.com/feed/update/urn:li:activity:{activity_id}/"
    # Profile URL fallback — send to their recent activity page so user can find the post
    if re.search(r'linkedin\.com/in/[^/?#]+/?$', url):
        return url.rstrip('/') + '/recent-activity/all/'
    return url


def _is_profile_url(url: str) -> bool:
    """Return True if the URL is a profile page, not a direct post link."""
    if not url:
        return False
    clean = url.rstrip('/')
    if 'feed/update/urn' in clean or '/posts/' in clean:
        return False
    return bool(re.search(r'linkedin\.com/in/[^/?#]+$', clean.replace('/recent-activity/all', '')))


def _format_post_date(sp: ScoredPost) -> str:
    """Return a human-friendly post date string."""
    if sp.post.post_date:
        return sp.post.post_date.strftime("%d %b %Y, %H:%M UTC")
    raw = sp.post.raw_date_str
    if raw:
        return raw
    return "—"


def _rec_config(rec: str) -> tuple[str, str, str]:
    """Return (label, color, bg) for a recommendation value."""
    return {
        "yes":   ("Respond",  "#15803d", "#dcfce7"),
        "maybe": ("Consider", "#b45309", "#fef9c3"),
        "no":    ("Skip",     "#b91c1c", "#fee2e2"),
    }.get(rec, ("Unknown", "#64748b", "#f1f5f9"))


def _cat_config(cat: str) -> tuple[str, str]:
    return {
        "technical": ("Technical", "#1d4ed8"),
        "hiring":    ("Hiring",    "#7c3aed"),
        "other":     ("Other",     "#64748b"),
    }.get(cat.lower(), (cat.title(), "#64748b"))


def _score_row(label: str, value: float, max_val: float = 10.0) -> str:
    pct = min(value / max_val * 100, 100)
    color = "#16a34a" if pct >= 70 else "#d97706" if pct >= 40 else "#dc2626"
    return (
        f'<div class="sr">'
        f'<span class="sr-lbl">{label}</span>'
        f'<div class="sr-bar"><div class="sr-fill" style="width:{pct:.0f}%;background:{color}"></div></div>'
        f'<span class="sr-val">{value:.1f}</span>'
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

    # ── Build post cards ─────────────────────────────────────────────────
    cards_html = ""
    for i, sp in enumerate(scored_posts):
        post_url     = _safe_post_url(sp.post_url)
        snippet_esc  = html.escape(sp.post_snippet or "")
        response_esc = html.escape(sp.suggested_response or "")
        reason_esc   = html.escape(sp.response_reason or "")
        author_esc   = html.escape(sp.author or "Unknown")
        keyword_esc  = html.escape(sp.keyword or "")
        post_date    = _format_post_date(sp)

        rec_label, rec_color, rec_bg = _rec_config(sp.respond_recommendation)
        cat_label, cat_color         = _cat_config(sp.category)
        has_response = bool(sp.suggested_response and sp.suggested_response.strip())
        is_profile   = _is_profile_url(post_url)
        link_label   = "View author activity ↗" if is_profile else "Open post ↗"
        link_title   = "Direct post link not available — opens author's recent activity" if is_profile else ""
        link_class   = "btn-view btn-view-profile" if is_profile else "btn-view"
        date_display = post_date if post_date != "—" else "Date unavailable"
        date_class   = "post-date post-date-missing" if post_date == "—" else "post-date"

        scores_html = (
            _score_row("Relevance",  sp.relevance_score) +
            _score_row("Engagement", sp.engagement_score) +
            _score_row("Freshness",  sp.freshness_score) +
            _score_row("Trending",   sp.trending_score)
        )

        response_html = ""
        if has_response:
            response_html = f"""
            <div class="response-area">
              <div class="response-toolbar">
                <span class="response-label">Suggested response</span>
                <div class="response-actions">
                  <button class="btn-copy" onclick="copyResp(this,'rt{i}')">Copy</button>
                  <button class="btn-responded" id="rb{i}" onclick="markResponded({i})">Mark Responded</button>
                </div>
              </div>
              <div id="rt{i}" class="response-text">{response_esc}</div>
            </div>"""

        cards_html += f"""
      <div class="card" id="card{i}" data-rec="{sp.respond_recommendation}" data-cat="{sp.category}"
           data-url="{html.escape(post_url)}"
           data-search="{html.escape((sp.author + ' ' + (sp.post_snippet or '')).lower())}">
        <div class="card-top" style="background:{rec_bg};">
          <div class="card-badges">
            <span class="badge" style="background:{rec_color};color:white;">{rec_label}</span>
            <span class="badge" style="background:{cat_color};color:white;">{cat_label}</span>
            <span class="badge-outline">Priority {sp.priority_score:.0f}</span>
          </div>
          <div class="card-top-right">
            <span class="{date_class}" title="Post date/time">🗓 {date_display}</span>
            <span class="responded-stamp" id="rs{i}" style="display:none;">✓ Responded</span>
            <a class="{link_class}" href="{post_url}" target="_blank" rel="noopener" title="{link_title}">{link_label}</a>
          </div>
        </div>

        <div class="card-body">
          <div class="card-main">
            <div class="author-row">
              <span class="author">{author_esc}</span>
              <span class="keyword-chip">{keyword_esc}</span>
            </div>
            <p class="snippet">{snippet_esc}</p>
            <div class="stats-row">
              <span>👍 {sp.likes:,}</span>
              {'<span>👁 ' + f'{sp.views:,}' + '</span>' if sp.views else ''}
              <span class="reason">· {reason_esc}</span>
            </div>
          </div>
          <div class="scores-col">
            {scores_html}
            <div class="priority-num">{sp.priority_score:.0f}<span class="priority-sub">/100</span></div>
          </div>
        </div>

        {response_html}
      </div>"""

    # ── Full HTML ─────────────────────────────────────────────────────────
    html_out = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Amazon Connect Intelligence · {run_ts}</title>
<style>
/* ── Reset ── */
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
     font-size:0.875rem;color:#1e293b;background:#eef2f7;min-height:100vh}}

/* ── Top bar ── */
.topbar{{background:#0f172a;color:white;padding:14px 28px;display:flex;
         justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px}}
.topbar h1{{font-size:1.1rem;font-weight:700;letter-spacing:.02em}}
.topbar .meta{{font-size:0.75rem;color:#94a3b8}}

/* ── Page ── */
.page{{max-width:1080px;margin:0 auto;padding:24px 16px 60px}}

/* ── Stats strip ── */
.stats-strip{{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:18px}}
.stat{{background:white;border:1px solid #e2e8f0;border-radius:10px;
       padding:12px 18px;min-width:110px;text-align:center}}
.stat .n{{font-size:1.9rem;font-weight:800;line-height:1}}
.stat .l{{font-size:0.68rem;text-transform:uppercase;letter-spacing:.06em;
          color:#94a3b8;margin-top:3px}}
.stat.yes .n{{color:#16a34a}} .stat.maybe .n{{color:#d97706}} .stat.no .n{{color:#dc2626}}
.stat.responded .n{{color:#6366f1}}

/* ── Toolbar ── */
.toolbar{{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:14px}}
.fb{{padding:5px 14px;border-radius:20px;border:1px solid #cbd5e1;
     background:white;font-size:0.78rem;cursor:pointer;color:#475569;transition:all .12s}}
.fb:hover,.fb.on{{background:#0f172a;color:white;border-color:#0f172a}}
.search{{padding:6px 12px;border:1px solid #e2e8f0;border-radius:6px;
         font-size:0.82rem;width:210px;color:#1e293b;background:white}}
.search:focus{{outline:none;border-color:#3b82f6}}
.count{{font-size:0.78rem;color:#94a3b8;margin-left:auto}}
.filter-bar{{background:white;border:1px solid #e2e8f0;border-radius:8px;
            padding:8px 14px;margin-bottom:14px;display:flex;gap:18px;
            flex-wrap:wrap;font-size:0.78rem;color:#64748b}}
.filter-bar strong{{color:#1e293b}}

/* ── Card ── */
.card{{background:white;border:1px solid #e2e8f0;border-radius:12px;
       margin-bottom:12px;overflow:hidden;transition:box-shadow .15s}}
.card:hover{{box-shadow:0 3px 14px rgba(0,0,0,.07)}}
.card[data-rec="yes"]  {{border-left:4px solid #16a34a}}
.card[data-rec="maybe"]{{border-left:4px solid #d97706}}
.card[data-rec="no"]   {{border-left:4px solid #dc2626}}
.card.responded{{opacity:.55}}

/* ── Card top bar ── */
.card-top{{display:flex;justify-content:space-between;align-items:center;
          padding:8px 14px;flex-wrap:wrap;gap:6px;border-bottom:1px solid rgba(0,0,0,.05)}}
.card-badges{{display:flex;gap:6px;align-items:center;flex-wrap:wrap}}
.badge{{padding:2px 10px;border-radius:20px;font-size:0.7rem;font-weight:600;letter-spacing:.02em}}
.badge-outline{{padding:2px 10px;border-radius:20px;font-size:0.7rem;color:#475569;
               background:#f1f5f9;border:1px solid #e2e8f0;font-weight:600}}
.card-top-right{{display:flex;gap:10px;align-items:center;flex-wrap:wrap}}
.post-date{{font-size:0.73rem;color:#64748b}}
.responded-stamp{{font-size:0.73rem;font-weight:600;color:#16a34a;
                 background:#dcfce7;padding:2px 8px;border-radius:10px}}
.btn-view{{font-size:0.78rem;font-weight:600;color:#2563eb;text-decoration:none;
          padding:3px 10px;border:1px solid #bfdbfe;border-radius:5px;background:#eff6ff}}
.btn-view:hover{{background:#2563eb;color:white;border-color:#2563eb}}
.btn-view-profile{{color:#7c3aed;border-color:#ddd6fe;background:#faf5ff}}
.btn-view-profile:hover{{background:#7c3aed;color:white;border-color:#7c3aed}}
.post-date-missing{{color:#94a3b8;font-style:italic}}

/* ── Card body ── */
.card-body{{display:flex;gap:14px;padding:12px 14px;align-items:flex-start}}
.card-main{{flex:1;min-width:0}}
.author-row{{display:flex;gap:10px;align-items:baseline;flex-wrap:wrap;margin-bottom:5px}}
.author{{font-weight:700;font-size:0.9rem;color:#0f172a}}
.keyword-chip{{font-size:0.7rem;color:#64748b;background:#f8fafc;
              padding:1px 8px;border-radius:10px;border:1px solid #e2e8f0}}
.snippet{{font-size:0.84rem;color:#334155;line-height:1.6;
         display:-webkit-box;-webkit-line-clamp:4;-webkit-box-orient:vertical;overflow:hidden;
         margin-bottom:8px}}
.stats-row{{display:flex;gap:14px;font-size:0.76rem;color:#64748b;flex-wrap:wrap}}
.reason{{font-style:italic;color:#94a3b8}}

/* ── Scores column ── */
.scores-col{{display:flex;flex-direction:column;gap:5px;min-width:148px}}
.sr{{display:flex;align-items:center;gap:5px}}
.sr-lbl{{font-size:0.68rem;color:#94a3b8;width:62px;text-align:right;white-space:nowrap}}
.sr-bar{{flex:1;height:5px;background:#e2e8f0;border-radius:3px;overflow:hidden}}
.sr-fill{{height:100%;border-radius:3px;transition:width .3s}}
.sr-val{{font-size:0.72rem;font-weight:600;color:#475569;width:22px}}
.priority-num{{text-align:right;font-size:1.5rem;font-weight:800;color:#0f172a;
              margin-top:4px;line-height:1}}
.priority-sub{{font-size:0.65rem;color:#94a3b8;font-weight:400}}

/* ── Response area ── */
.response-area{{border-top:1px solid #f1f5f9;background:#f8fafc;padding:12px 14px}}
.response-toolbar{{display:flex;align-items:center;gap:8px;margin-bottom:7px}}
.response-label{{font-size:0.73rem;font-weight:700;text-transform:uppercase;
                letter-spacing:.06em;color:#64748b}}
.response-actions{{margin-left:auto;display:flex;gap:6px}}
.btn-copy,.btn-responded{{padding:3px 10px;font-size:0.75rem;border-radius:5px;
                          border:1px solid #cbd5e1;background:white;cursor:pointer;color:#475569}}
.btn-copy:hover{{background:#0f172a;color:white;border-color:#0f172a}}
.btn-responded{{border-color:#bbf7d0;color:#16a34a}}
.btn-responded:hover,.btn-responded.done{{background:#16a34a;color:white;border-color:#16a34a}}
.response-text{{font-size:0.875rem;line-height:1.7;color:#1e293b;
               white-space:pre-wrap;font-family:inherit}}

/* ── Hidden ── */
.card.hidden{{display:none}}

/* ── Responsive ── */
@media(max-width:680px){{
  .card-body{{flex-direction:column}}
  .scores-col{{flex-direction:row;flex-wrap:wrap;min-width:unset}}
}}
</style>
</head>
<body>

<div class="topbar">
  <h1>Amazon Connect Intelligence</h1>
  <span class="meta">Generated {run_ts} &nbsp;·&nbsp; {html.escape(keywords_str)}</span>
</div>

<div class="page">

<div class="stats-strip">
  <div class="stat"><div class="n">{len(scored_posts)}</div><div class="l">Scored</div></div>
  <div class="stat yes"><div class="n">{yes_count}</div><div class="l">Respond</div></div>
  <div class="stat maybe"><div class="n">{maybe_count}</div><div class="l">Consider</div></div>
  <div class="stat no"><div class="n">{no_count}</div><div class="l">Skip</div></div>
  <div class="stat responded"><div class="n" id="responded-count">0</div><div class="l">Responded</div></div>
</div>

<div class="filter-bar">
  <span>Min likes: <strong>{f.min_likes}</strong></span>
  <span>Min views: <strong>{f.min_views}</strong></span>
  <span>Lookback: <strong>{f.lookback_days} days</strong></span>
</div>

<div class="toolbar">
  <button class="fb on" onclick="setRec('all',this)">All</button>
  <button class="fb" onclick="setRec('yes',this)">Respond</button>
  <button class="fb" onclick="setRec('maybe',this)">Consider</button>
  <button class="fb" onclick="setRec('no',this)">Skip</button>
  <button class="fb" onclick="setRec('responded',this)">Responded</button>
  <button class="fb" onclick="setRec('pending',this)">Not Responded</button>
  <input class="search" type="text" placeholder="Search author or text…" oninput="doSearch(this.value)">
  <span class="count" id="cnt">{len(scored_posts)} posts</span>
</div>

<div id="cards">
{cards_html}
</div>

</div>

<script>
// Responded state is stored in localStorage — persists on disk across sessions and reboots.
// Keyed by post URL (stable across runs), using a fixed key shared across all reports.
var STORE_KEY = 'li_connect_responded';
var responded = JSON.parse(localStorage.getItem(STORE_KEY) || '{{}}');
var recFilter = 'all';
var searchVal = '';

// Restore responded state on page load
document.querySelectorAll('.card[data-url]').forEach(function(card) {{
  var url = card.getAttribute('data-url');
  if (url && responded[url]) {{
    setRespondedUI(card.id.replace('card', ''), true);
  }}
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

function setRespondedUI(i, isResponded) {{
  var card  = document.getElementById('card' + i);
  var stamp = document.getElementById('rs' + i);
  var btn   = document.getElementById('rb' + i);
  if (!card) return;
  if (isResponded) {{
    card.classList.add('responded');
    if (stamp) stamp.style.display = 'inline-flex';
    if (btn)   {{ btn.textContent = 'Undo'; btn.classList.add('done'); }}
  }} else {{
    card.classList.remove('responded');
    if (stamp) stamp.style.display = 'none';
    if (btn)   {{ btn.textContent = 'Mark Responded'; btn.classList.remove('done'); }}
  }}
}}

function updateRespondedCount() {{
  // Count only URLs that appear in this report
  var n = 0;
  document.querySelectorAll('.card[data-url]').forEach(function(card) {{
    if (responded[card.getAttribute('data-url')]) n++;
  }});
  var el = document.getElementById('responded-count');
  if (el) el.textContent = n;
}}

function setRec(r, btn) {{
  recFilter = r;
  document.querySelectorAll('.fb').forEach(function(b) {{ b.classList.remove('on'); }});
  btn.classList.add('on');
  applyFilters();
}}

function doSearch(v) {{
  searchVal = v.toLowerCase();
  applyFilters();
}}

function applyFilters() {{
  var cards = document.querySelectorAll('.card');
  var n = 0;
  cards.forEach(function(card) {{
    var url = card.getAttribute('data-url');
    var isResponded = responded[url];
    var recOk = recFilter === 'all'
      || (recFilter === 'pending'   && !isResponded)
      || (recFilter === 'responded' &&  isResponded)
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
    btn.style.background = '#16a34a';
    btn.style.color = 'white';
    setTimeout(function() {{
      btn.textContent = orig;
      btn.style.background = '';
      btn.style.color = '';
    }}, 2000);
  }});
}}
</script>
</body>
</html>"""

    with open(path, "w", encoding="utf-8") as out:
        out.write(html_out)

    return path


# ── Email-safe HTML report ─────────────────────────────────────────────────────
# Email clients (Gmail, Outlook) strip JavaScript and most CSS.
# This version uses only inline styles, no JS, no CSS variables.
# Only "Respond" and "Consider" posts are included — Skip posts are omitted.

def generate_email_html(
    scored_posts: list[ScoredPost],
    config: AppConfig,
    run_ts: str = "",
) -> str:
    """Return a self-contained email-safe HTML string (no JS, inline styles only)."""
    run_ts = run_ts or datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Only include actionable posts in the email
    email_posts = [sp for sp in scored_posts if sp.respond_recommendation in ("yes", "maybe")]
    yes_count   = sum(1 for s in scored_posts if s.respond_recommendation == "yes")
    maybe_count = sum(1 for s in scored_posts if s.respond_recommendation == "maybe")
    no_count    = sum(1 for s in scored_posts if s.respond_recommendation == "no")
    total_count = len(scored_posts)

    REC_STYLE = {
        "yes":   ("Respond",  "#15803d", "#dcfce7", "#166534"),
        "maybe": ("Consider", "#b45309", "#fef9c3", "#92400e"),
    }

    def inline_score_bar(label: str, value: float) -> str:
        pct = min(int(value / 10 * 100), 100)
        bar_color = "#16a34a" if pct >= 70 else "#d97706" if pct >= 40 else "#dc2626"
        return (
            f'<tr>'
            f'<td style="font-size:11px;color:#94a3b8;width:70px;text-align:right;'
            f'padding-right:6px;white-space:nowrap;">{label}</td>'
            f'<td style="width:80px;">'
            f'<div style="background:#e2e8f0;border-radius:3px;height:5px;overflow:hidden;">'
            f'<div style="background:{bar_color};width:{pct}%;height:5px;"></div>'
            f'</div></td>'
            f'<td style="font-size:11px;font-weight:700;color:#475569;'
            f'padding-left:5px;width:28px;">{value:.1f}</td>'
            f'</tr>'
        )

    cards_html = ""
    for sp in email_posts:
        post_url     = _safe_post_url(sp.post_url)
        snippet_esc  = html.escape(sp.post_snippet or "")
        response_esc = html.escape(sp.suggested_response or "")
        reason_esc   = html.escape(sp.response_reason or "")
        author_esc   = html.escape(sp.author or "Unknown")
        keyword_esc  = html.escape(sp.keyword or "")
        post_date    = _format_post_date(sp)

        rec_label, rec_bg, _, rec_txt = REC_STYLE.get(
            sp.respond_recommendation, ("Unknown", "#f1f5f9", "#64748b", "#475569")
        )
        cat_label, _ = _cat_config(sp.category)
        is_profile   = _is_profile_url(post_url)
        link_label   = "View author activity →" if is_profile else "Open post →"
        link_color   = "#7c3aed" if is_profile else "#2563eb"

        score_rows = (
            inline_score_bar("Relevance",  sp.relevance_score) +
            inline_score_bar("Engagement", sp.engagement_score) +
            inline_score_bar("Freshness",  sp.freshness_score) +
            inline_score_bar("Trending",   sp.trending_score)
        )

        response_block = ""
        if sp.suggested_response and sp.suggested_response.strip():
            response_block = f"""
            <tr><td colspan="2" style="padding:10px 14px;background:#f8fafc;
                border-top:1px solid #e2e8f0;">
              <div style="font-size:10px;font-weight:700;text-transform:uppercase;
                   letter-spacing:.06em;color:#94a3b8;margin-bottom:6px;">
                Suggested Response
              </div>
              <div style="font-size:13px;line-height:1.7;color:#1e293b;
                   white-space:pre-wrap;">{response_esc}</div>
            </td></tr>"""

        cards_html += f"""
        <table width="100%" cellpadding="0" cellspacing="0" border="0"
               style="margin-bottom:14px;border:1px solid #e2e8f0;border-radius:10px;
                      border-left:4px solid {rec_txt};overflow:hidden;
                      font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Arial,sans-serif;">
          <!-- Card header -->
          <tr style="background:{rec_bg};">
            <td style="padding:8px 14px;vertical-align:middle;">
              <span style="display:inline-block;padding:2px 10px;border-radius:20px;
                    font-size:10px;font-weight:700;background:{rec_txt};color:white;
                    margin-right:6px;">{rec_label}</span>
              <span style="display:inline-block;padding:2px 10px;border-radius:20px;
                    font-size:10px;font-weight:600;background:#1d4ed8;color:white;
                    margin-right:6px;">{cat_label}</span>
              <span style="font-size:10px;color:#64748b;font-weight:600;">
                Priority {sp.priority_score:.0f}/100</span>
            </td>
            <td style="padding:8px 14px;text-align:right;vertical-align:middle;white-space:nowrap;">
              <span style="font-size:11px;color:#64748b;margin-right:10px;">
                &#128197; {html.escape(post_date)}</span>
              <a href="{html.escape(post_url)}" style="font-size:11px;font-weight:700;
                 color:{link_color};text-decoration:none;">{link_label}</a>
            </td>
          </tr>
          <!-- Card body -->
          <tr>
            <td style="padding:12px 14px;vertical-align:top;background:white;">
              <div style="font-weight:700;font-size:14px;color:#0f172a;margin-bottom:3px;">
                {author_esc}
                <span style="font-size:10px;font-weight:400;color:#94a3b8;
                      background:#f8fafc;border:1px solid #e2e8f0;
                      padding:1px 7px;border-radius:10px;margin-left:6px;">{keyword_esc}</span>
              </div>
              <div style="font-size:13px;color:#334155;line-height:1.6;margin-bottom:8px;">
                {snippet_esc}
              </div>
              <div style="font-size:11px;color:#94a3b8;">
                &#128077; {sp.likes:,}
                {"&nbsp;&nbsp;&#128065; " + f"{sp.views:,}" if sp.views else ""}
                &nbsp;&nbsp;{reason_esc}
              </div>
            </td>
            <td style="padding:12px 14px;vertical-align:top;background:white;
                       width:170px;border-left:1px solid #f1f5f9;">
              <table cellpadding="2" cellspacing="0" border="0">
                {score_rows}
              </table>
              <div style="font-size:26px;font-weight:800;color:#0f172a;
                   text-align:right;margin-top:6px;line-height:1;">
                {sp.priority_score:.0f}<span style="font-size:11px;font-weight:400;
                color:#94a3b8;">/100</span>
              </div>
            </td>
          </tr>
          {response_block}
        </table>"""

    # Summary stats table
    f = config.filters
    stats_html = f"""
    <table cellpadding="0" cellspacing="8" border="0" style="margin-bottom:12px;">
      <tr>
        {_stat_cell(str(total_count), "Scored",    "#1e293b")}
        {_stat_cell(str(yes_count),   "Respond",   "#16a34a")}
        {_stat_cell(str(maybe_count), "Consider",  "#d97706")}
        {_stat_cell(str(no_count),    "Skip",      "#dc2626")}
        {_stat_cell("—",              "Responded", "#6366f1")}
      </tr>
    </table>
    <div style="font-size:11px;color:#94a3b8;margin-bottom:16px;">
      Min likes: <strong style="color:#475569;">{f.min_likes}</strong>
      &nbsp;·&nbsp; Min views: <strong style="color:#475569;">{f.min_views}</strong>
      &nbsp;·&nbsp; Lookback: <strong style="color:#475569;">{f.lookback_days} days</strong>
    </div>"""

    keywords_str = html.escape(", ".join(config.keywords))

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Amazon Connect Intelligence · {html.escape(run_ts)}</title>
</head>
<body style="margin:0;padding:0;background:#eef2f7;font-family:-apple-system,
     BlinkMacSystemFont,'Segoe UI',Arial,sans-serif;">

<table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#eef2f7;">
<tr><td align="center" style="padding:24px 16px;">

  <table width="640" cellpadding="0" cellspacing="0" border="0"
         style="max-width:640px;width:100%;">

    <!-- Header bar -->
    <tr>
      <td style="background:#0f172a;border-radius:10px 10px 0 0;
          padding:16px 24px;">
        <div style="font-size:17px;font-weight:700;color:white;
             letter-spacing:.02em;">Amazon Connect Intelligence</div>
        <div style="font-size:11px;color:#94a3b8;margin-top:3px;">
          Generated {html.escape(run_ts)} &nbsp;·&nbsp; {keywords_str}
        </div>
      </td>
    </tr>

    <!-- Stats + cards -->
    <tr>
      <td style="background:#eef2f7;padding:16px 0;">
        {stats_html}
        {cards_html}
      </td>
    </tr>

    <!-- Footer -->
    <tr>
      <td style="padding:16px 0;text-align:center;font-size:11px;color:#94a3b8;">
        Amazon Connect Intelligence · LinkedIn Post Scraper
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
