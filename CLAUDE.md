# Project Rules

Follow these instructions strictly when generating code.

---

## Core Principles
- Always produce complete, runnable code
- Do not omit files or use placeholders like "..."
- Favor practical, working solutions over theory
- Keep implementation simple and modular
- Do not overengineer

---

## Tech Stack & Constraints
- Python 3.11+
- Virtual environment: `.venv/` in project root
- Run with: `.venv/bin/python3 main.py`
- Add structured logging at info/debug level
- Local execution only (macOS terminal)
- Free and open-source tools only (except OpenAI API for scoring)
- Playwright for scraping (Chromium)
- No hardcoded secrets (use `.env` file)

---

## Project Structure

```
LinkedInScrapper/
├── main.py                  # Orchestration entry point
├── requirements.txt
├── config.yaml              # All runtime configuration
├── .env                     # LINKEDIN_EMAIL, LINKEDIN_PASSWORD, OPENAI_API_KEY, EMAIL_FROM, EMAIL_PASSWORD, EMAIL_TO
├── .env.example
├── .gitignore
├── README.md
├── CLAUDE.md
└── src/
    ├── config.py            # YAML + .env loader, typed AppConfig dataclasses
    ├── models.py            # Post, ScoredPost dataclasses
    ├── logging_setup.py     # File + console logging
    ├── scraper.py           # Playwright scraper (keyword search + profile activity)
    ├── parser.py            # Normalise raw post dicts → Post objects + extract_profile_id()
    ├── filtering.py         # likes/views/lookback/language filters (langdetect)
    ├── ai.py                # OpenAI scoring + response generation
    ├── storage.py           # SQLite upsert + cache
    ├── reporting.py         # HTML report generation (no CSV)
    ├── reporting_v1_backup.py  # Backup: original table-based style
    ├── reporting_v2_backup.py  # Backup: previous card-based style
    └── emailer.py           # Optional Gmail SMTP
├── test_email.py            # Standalone email test (uses existing DB, no scraping)
```

Runtime directories created automatically: `reports/`, `data/`, `logs/`

---

## Configuration (`config.yaml`)

```yaml
keywords:
  - "Amazon Connect"
  - "Amazon Connect contact center"
  - "AWS contact center"
  - "CCaaS AWS"
  - "Amazon Lex contact center"
  - "Amazon Polly contact center"
  - "Contact Lens Amazon"
  - "Amazon Q Connect"
  - "AWS CCP agent"
  - "Amazon Connect Wisdom"

profiles:                    # Always-scrape profiles regardless of keyword results
  - ramprasadsrirama
  - jerrydimos
  # ... (see config.yaml for full list)

filters:
  min_likes: 5
  min_views: 0
  lookback_days: 7
  include_if_no_date: true

scraping:
  max_posts_per_keyword: 50
  headless: false
  scroll_pause_ms: 1500
  max_retries: 3

output:
  reports_dir: reports
  data_dir: data
  logs_dir: logs

ai:
  model: gpt-4o-mini
  response_mode: engage      # engage | deep | question | contrarian

categories:
  respond_to:
    - technical
  exclude_categories:
    - hiring
    - other

email:
  enabled: true
  # Recipient is read from EMAIL_TO in .env
```

---

## Scraping Pipeline

### Two-phase approach

**Phase 1 — Keyword search:**
- URL: `https://www.linkedin.com/search/results/content/?keywords=%22{keyword}%22&sortBy=%22date_posted%22&origin=FACETED_SEARCH`
- Uses double-quoted keyword for exact phrase match
- JS extractor `_EXTRACT_JS` finds posts via `[aria-label*="Open control menu for post"]`, container is 2 levels up
- After collection, `_enrich_post_urls()` clicks "..." → "Copy link to post" via clipboard intercept for posts lacking direct URLs
- After scoring, authors of `yes`/`maybe` `technical` posts are auto-discovered and queued for Phase 2

**Phase 2 — Profile activity pages:**
- URL: `https://www.linkedin.com/in/{profile_id}/recent-activity/all/`
- Separate JS extractor `_EXTRACT_PROFILE_JS` — uses `role="article"` containers with `.update-components-text` for post text
- Post URL derived from `data-urn="urn:li:activity:{id}"` attribute → `/feed/update/urn:li:activity:{id}/`
- Profiles seeded from `config.yaml profiles:` + auto-discovered from Phase 1

### Post URL format
All post URLs normalised to `/feed/update/urn:li:activity:{id}/` — always resolves correctly.
Profile-only fallback URLs are redirected to `/in/{slug}/recent-activity/all/` in the report.

### Clipboard intercept
Injected as a browser context `add_init_script` before any navigation:
```js
window.__clipboardCapture = null;
navigator.clipboard.writeText = async (text) => { window.__clipboardCapture = text; ... };
```

### Scroll containers
- Search results: `main#workspace` (not `window`)
- Profile pages: `main` or `.scaffold-layout__main`

---

## Filtering (`src/filtering.py`)
Applied in order:
1. `likes >= min_likes`
2. `views >= min_views`
3. Post age within `lookback_days` (or `include_if_no_date` fallback)
4. English-only via `langdetect` — non-English posts rejected

---

## Post Categories

| Category | Description |
|---|---|
| `technical` | AWS/cloud architecture, Amazon Connect features, product launches, engineering lessons, hands-on insights |
| `hiring` | Job postings, open roles, recruiting, career advice, headcount |
| `other` | Certification announcements, new-job celebrations, personal milestones, motivational content, marketing |

- **`respond_to`** — categories that receive `suggested_response`
- **`exclude_categories`** — categories removed from report entirely after AI scoring

---

## AI Scoring (`src/ai.py`)

### OpenAI call (JSON mode, gpt-4o-mini)
Returns per post:
- `category` — technical / hiring / other
- `relevance_score` — 0–10
- `engagement_score` — 0–10
- `response_value_score` — 0–10
- `response_mode` — engage / deep / question / contrarian
- `response_reason` — one sentence
- `suggested_response` — practitioner-voice comment (or "" if not in respond_to)

### Locally computed scores
- `freshness_score`: 0–1d → 9.5, 2–3d → 7.5, 4–5d → 5.5, 6–7d → 3.5, missing → 5.0
- `trending_score`: `min((likes + views×0.1) / age / 500 × 10, 10)`
- `priority_score`: `relevance×3.5 + response_value×2.5 + engagement×1.5 + freshness×1.0 + trending×1.5` (max 100)
- `respond_recommendation`: ≥70 → yes, 45–69 → maybe, <45 → no

### Response voice
- Senior Amazon Connect SA persona — writes like a colleague at re:Invent
- References author by first name only when it flows naturally
- For new-feature posts: concrete use case only when genuinely relevant
- For lessons/architecture: builds on the post with a related angle or contrast
- No bullet points, no hashtags, no emojis, 3–5 sentences
- Does NOT end with a question unless `response_mode` is `question`
- Questions in `question` mode must be grounded in the specific post — no generic architectural questions

---

## Storage (`src/storage.py`)
- SQLite at `data/posts.db`
- `needs_ai_rescore()` — True if post is new or likes/views changed
- `get_cached_scored_post()` — returns cached ScoredPost if unchanged
- Upsert on `post_url` primary key

---

## HTML Report (`src/reporting.py`)
Enterprise card-based layout with dark navy topbar (sticky), amber "AC" logo, and `#F0F4F8` background.

Each post card shows:
- **Header**: color-coded left border + background, rec badge, category badge, priority badge, post date, link button
- **Body left**: author name, keyword chip, post snippet (4 lines), likes/views, AI reason
- **Body right**: 4 score bars (Relevance, Engagement, Freshness, Trending) + large priority number, separated by a subtle vertical rule
- **Response panel**: `#FAFBFD` background, "Suggested Response" label, Copy + "Mark Responded" buttons
- Cards lift slightly on hover

### Link types
- Direct post link → blue "Open Post ↗" button
- Profile fallback URL → purple "View Activity ↗" (redirects to recent-activity page)

### Interactive controls
- Sticky toolbar: All / Respond / Consider / Skip / Responded / Not Responded filter buttons + search box + live count
- Full-text search (author + post text)

### Responded state persistence
- Stored in `localStorage` under fixed key `li_connect_responded`
- Keyed by post URL — survives across runs and multiple reports
- "Responded" count in stats strip updates live

## Email Report (`src/reporting.py` → `generate_email_html()`)
- Separate email-safe HTML generator — inline styles only, no JS, table-based layout
- Renders correctly in Gmail and Outlook
- Shows only Respond + Consider posts (Skip omitted)
- Same design language as the local report: dark header, stats strip, score bars, response block
- Recipient read from `EMAIL_TO` in `.env`; sender from `EMAIL_FROM` + `EMAIL_PASSWORD`
- Test without scraping: `.venv/bin/python3 test_email.py`

---

## Sorting (`main.py`)
```python
key = (rec_order[sp.respond_recommendation], -sp.priority_score,
       -sp.trending_score, -sp.freshness_score, -sp.views)
```

---

## Output
- **HTML report** only — no CSV generated
- Terminal prints a `file://` URL for one-click opening
- Email sent automatically if `email.enabled: true` in `config.yaml` and `EMAIL_TO` is set in `.env`
- Logs: `logs/scraper_YYYYMMDD.log`

---

## Reliability
- Retries with exponential backoff for OpenAI calls
- Per-keyword / per-profile failures are caught and logged — run continues
- Login: uses `domcontentloaded` + `wait_for_selector` with retry on both `input[name="session_key"]` and `input#username`
- Verification checkpoint: pauses 120s for manual CAPTCHA/phone completion
- Screenshot saved to `logs/login_challenge.png` on checkpoint

---

## Running the program

```bash
# First-time setup
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/playwright install chromium

# Configure credentials
cp .env.example .env
# Edit .env: LINKEDIN_EMAIL, LINKEDIN_PASSWORD, OPENAI_API_KEY

# Run
.venv/bin/python3 main.py

# With a different config file
.venv/bin/python3 main.py --config path/to/config.yaml
```

---

## Output Rules
When generating code:
1. Show full project tree first
2. Then output every file in full
3. Do not skip anything
4. Do not summarise code
