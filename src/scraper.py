from __future__ import annotations

import asyncio
import logging
import random
import urllib.parse
from typing import Optional

from playwright.async_api import BrowserContext, Page, async_playwright

from src.config import AppConfig

logger = logging.getLogger("linkedin_scraper")

# Double-quoted keyword ensures exact phrase match.
# sortBy=%22date_posted%22 sorts by most recent.
# &origin=FACETED_SEARCH limits to posts (Content type).
SEARCH_URL = (
    "https://www.linkedin.com/search/results/content/"
    '?keywords=%22{keyword}%22&sortBy=%22date_posted%22&origin=FACETED_SEARCH'
)

# Clipboard init script — captures the text passed to navigator.clipboard.writeText.
# Injected before any page navigation so it survives page loads.
_CLIPBOARD_INTERCEPT_JS = """
window.__clipboardCapture = null;
const _origWrite = navigator.clipboard.writeText.bind(navigator.clipboard);
navigator.clipboard.writeText = async (text) => {
    window.__clipboardCapture = text;
    return _origWrite(text);
};
"""

# ---------------------------------------------------------------------------
# JavaScript-based post extraction — SEARCH RESULTS
# LinkedIn 2025/2026 uses hashed CSS classes — we use semantic/attribute selectors.
# ---------------------------------------------------------------------------

_EXTRACT_JS = r"""
(keyword) => {
    const posts = [];
    // Each post has a control-menu button — use it as the anchor.
    const ctrlBtns = document.querySelectorAll('[aria-label*="Open control menu for post"]');

    for (const btn of ctrlBtns) {
        try {
            // The full post container is 2 levels up from the control-menu button.
            const container = btn.parentElement && btn.parentElement.parentElement;
            if (!container) continue;

            // --- Author & author profile URL ---
            let author = '';
            let authorProfileUrl = '';
            const inLinks = container.querySelectorAll('a[href*="/in/"]');
            for (const link of inLinks) {
                const txt = link.textContent.trim();
                if (txt && txt.length > 2) {
                    // Remove "• 3rd+" type connection degree suffixes
                    author = txt.split('\u2022')[0].split('•')[0].trim();
                    authorProfileUrl = link.href || '';
                    break;
                }
            }

            // --- Post text ---
            const textEl = container.querySelector('[data-testid="expandable-text-box"]');
            const postText = textEl ? textEl.textContent.trim().substring(0, 400) : '';

            // --- Post URL ---
            // Priority: /posts/ link > /feed/update/ link > activity link > author profile
            let postUrl = '';

            // 1. Direct /posts/ links (present on profile activity pages and some search results)
            const postLinks = container.querySelectorAll('a[href*="/posts/"]');
            if (postLinks.length) {
                postUrl = postLinks[0].href;
            }

            // 2. /feed/update/ links
            if (!postUrl) {
                const feedLinks = container.querySelectorAll('a[href*="/feed/update/"]');
                if (feedLinks.length) {
                    postUrl = feedLinks[0].href;
                }
            }

            // 3. Any activity link
            if (!postUrl) {
                const allLinks = container.querySelectorAll('a[href]');
                for (const a of allLinks) {
                    const href = a.href || '';
                    if (href.includes('activity') && href.includes('linkedin.com')) {
                        postUrl = href;
                        break;
                    }
                }
            }

            // 4. Fall back to author profile URL as stable dedup identifier
            if (!postUrl && authorProfileUrl) {
                postUrl = authorProfileUrl;
            }

            // --- Likes ---
            let likesStr = '0';
            const numSpans = container.querySelectorAll('span[aria-hidden="true"]');
            for (const s of numSpans) {
                const t = s.textContent.trim();
                if (/^[\d,.]+[KkMm]?$/.test(t) && t !== '0') {
                    likesStr = t;
                    break;
                }
            }
            const reactionBtn = container.querySelector('[aria-label*="reaction"]');
            if (reactionBtn) {
                const label = reactionBtn.getAttribute('aria-label') || '';
                const m = label.match(/([\d,.]+[KkMm]?)\s*reaction/i);
                if (m) likesStr = m[1];
            }

            // --- Views / impressions ---
            let viewsStr = '0';
            const allSpans = container.querySelectorAll('span, button');
            for (const s of allSpans) {
                const label = (s.getAttribute('aria-label') || '').toLowerCase();
                if (label.includes('impression') || label.includes('view')) {
                    const m = label.match(/([\d,.]+[KkMm]?)/);
                    if (m) { viewsStr = m[1]; break; }
                }
                const txt = s.textContent.trim().toLowerCase();
                if ((txt.endsWith('impressions') || txt.endsWith('views')) && txt.length < 30) {
                    viewsStr = txt.replace(/[^\d,.KkMm]/g, '').trim() || '0';
                    break;
                }
            }

            // --- Date ---
            let rawDate = '';
            const timeEl = container.querySelector('time');
            if (timeEl) {
                rawDate = timeEl.getAttribute('datetime') || timeEl.textContent.trim();
            }
            if (!rawDate) {
                const candidates = container.querySelectorAll('span, a');
                for (const el of candidates) {
                    const t = el.textContent.trim();
                    if (/^\d+[smhdwmy]$/.test(t) ||
                        /^\d+ (second|minute|hour|day|week|month|year)/i.test(t)) {
                        rawDate = t;
                        break;
                    }
                }
            }

            if (!postText && !author) continue;

            posts.push({
                keyword: keyword,
                author: author,
                author_profile_url: authorProfileUrl,
                post_snippet: postText.substring(0, 300),
                post_url: postUrl,
                likes_str: likesStr,
                views_str: viewsStr,
                raw_date_str: rawDate,
            });
        } catch (e) {
            // skip failed element
        }
    }
    return posts;
}
"""


# ---------------------------------------------------------------------------
# JavaScript-based post extraction — PROFILE ACTIVITY PAGES
# Profile pages use role="article" / .feed-shared-update-v2 containers.
# Text is in .update-components-text (not [data-testid="expandable-text-box"]).
# Date is in a visually-hidden span. URL is derived from data-urn attribute.
# ---------------------------------------------------------------------------

_EXTRACT_PROFILE_JS = """
(keyword) => {
    const posts = [];
    // Profile activity posts are role=article elements
    const articles = document.querySelectorAll('[role="article"]');

    for (const article of articles) {
        try {
            // --- Post text ---
            // Try multiple selectors; profile pages use update-components-text
            let postText = '';
            const textSelectors = [
                '.update-components-text',
                '.feed-shared-inline-show-more-text',
                '.break-words',
                '[data-testid="expandable-text-box"]',
            ];
            for (const sel of textSelectors) {
                const el = article.querySelector(sel);
                if (el) {
                    postText = el.textContent.trim().substring(0, 400);
                    if (postText.length > 20) break;
                }
            }

            // --- Author & profile URL ---
            let author = '';
            let authorProfileUrl = '';
            // The actor meta link has name + title
            const actorLink = article.querySelector('.update-components-actor__meta-link, a[href*="/in/"]');
            if (actorLink) {
                authorProfileUrl = actorLink.href || '';
                // The name is in the title span
                const nameEl = actorLink.querySelector('.update-components-actor__title span[dir="ltr"] span[aria-hidden="true"]')
                    || actorLink.querySelector('span[dir="ltr"] span[aria-hidden="true"]');
                if (nameEl) {
                    author = nameEl.textContent.trim();
                } else {
                    // Fall back: get text from link, strip connection degree suffixes
                    author = actorLink.textContent.split('\u2022')[0].split('•')[0].trim().split('\\n')[0].trim();
                }
            }

            // --- Post URL from data-urn ---
            // data-urn = "urn:li:activity:7445158642720358402"
            // Use /feed/update/urn:li:activity:... format — always resolves correctly.
            let postUrl = '';
            const urn = article.getAttribute('data-urn') || '';
            if (urn && urn.includes('activity')) {
                postUrl = `https://www.linkedin.com/feed/update/${urn}/`;
            }
            // Fallback: /posts/ links (have correct slug already)
            if (!postUrl) {
                const postLink = article.querySelector('a[href*="/posts/"]');
                if (postLink) postUrl = postLink.href;
            }
            // Fallback: /feed/update/ links
            if (!postUrl) {
                const feedLink = article.querySelector('a[href*="/feed/update/"]');
                if (feedLink) postUrl = feedLink.href;
            }

            // --- Likes ---
            let likesStr = '0';
            const reactionBtn = article.querySelector('[aria-label*="reaction"]');
            if (reactionBtn) {
                const m = (reactionBtn.getAttribute('aria-label') || '').match(/([\\d,.]+[KkMm]?)\\s*reaction/i);
                if (m) likesStr = m[1];
            }
            if (likesStr === '0') {
                const numSpans = article.querySelectorAll('span[aria-hidden="true"]');
                for (const s of numSpans) {
                    const t = s.textContent.trim();
                    if (/^[\\d,.]+[KkMm]?$/.test(t) && t !== '0') { likesStr = t; break; }
                }
            }

            // --- Views ---
            let viewsStr = '0';
            for (const el of article.querySelectorAll('span, button')) {
                const lbl = (el.getAttribute('aria-label') || '').toLowerCase();
                if (lbl.includes('impression') || lbl.includes('view')) {
                    const m = lbl.match(/([\\d,.]+[KkMm]?)/);
                    if (m) { viewsStr = m[1]; break; }
                }
                const txt = el.textContent.trim().toLowerCase();
                if ((txt.endsWith('impressions') || txt.endsWith('views')) && txt.length < 30) {
                    viewsStr = txt.replace(/[^\\d,.KkMm]/g, '').trim() || '0';
                    break;
                }
            }

            // --- Date ---
            // Profile pages often show date in a visually-hidden span: "3 days ago • ..."
            let rawDate = '';
            const hiddenSpans = article.querySelectorAll('.visually-hidden');
            for (const s of hiddenSpans) {
                const t = s.textContent.trim();
                if (/\\d+\\s*(second|minute|hour|day|week|month|year|mo|hr|min|sec)/i.test(t) ||
                    /\\d+[smhdwmy]\\b/.test(t)) {
                    rawDate = t.split('•')[0].trim();
                    break;
                }
            }
            // Also try time element
            if (!rawDate) {
                const timeEl = article.querySelector('time');
                if (timeEl) rawDate = timeEl.getAttribute('datetime') || timeEl.textContent.trim();
            }
            // Fallback: look for a[aria-label*="ago"] or span[aria-label*="ago"]
            if (!rawDate) {
                const agoEl = article.querySelector('[aria-label*=" ago"]');
                if (agoEl) rawDate = (agoEl.getAttribute('aria-label') || '').split('•')[0].trim();
            }

            if (!postText && !author) continue;

            posts.push({
                keyword: keyword,
                author: author,
                author_profile_url: authorProfileUrl,
                post_snippet: postText.substring(0, 300),
                post_url: postUrl,
                likes_str: likesStr,
                views_str: viewsStr,
                raw_date_str: rawDate,
            });
        } catch (e) {
            // skip failed element
        }
    }
    return posts;
}
"""


async def _extract_all_posts_js(page: Page, keyword: str) -> list[dict]:
    """Run the search-results JS extractor in the page context."""
    try:
        return await page.evaluate(_EXTRACT_JS, keyword)
    except Exception as e:
        logger.warning(f"JS extraction error: {e}")
        return []


async def _extract_profile_posts_js(page: Page, keyword: str) -> list[dict]:
    """Run the profile-activity JS extractor in the page context."""
    try:
        return await page.evaluate(_EXTRACT_PROFILE_JS, keyword)
    except Exception as e:
        logger.warning(f"Profile JS extraction error: {e}")
        return []


# ---------------------------------------------------------------------------
# Main scraper class
# ---------------------------------------------------------------------------

class LinkedInScraper:
    def __init__(self, config: AppConfig):
        self._config = config
        self._playwright = None
        self._browser = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None

    async def __aenter__(self) -> "LinkedInScraper":
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=self._config.scraping.headless
        )
        self._context = await self._browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        )
        # Inject clipboard intercept before any page load
        await self._context.add_init_script(_CLIPBOARD_INTERCEPT_JS)
        self._page = await self._context.new_page()
        return self

    async def __aexit__(self, *args) -> None:
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    async def login(self, email: str, password: str) -> bool:
        page = self._page
        logger.info("Navigating to LinkedIn login page...")

        for attempt in range(2):
            try:
                await page.goto(
                    "https://www.linkedin.com/login",
                    wait_until="domcontentloaded",
                    timeout=30000,
                )
            except Exception:
                pass
            await asyncio.sleep(2)

            current_url = page.url
            logger.info(f"Landed on: {current_url}")

            if self._is_logged_in(current_url):
                logger.info("Already logged in")
                return True

            # Wait for login form — up to 30s
            try:
                await page.wait_for_selector(
                    'input[name="session_key"], input#username',
                    timeout=30000,
                )
                break  # form found
            except Exception:
                if attempt == 0:
                    logger.warning("Login form not found — retrying navigation")
                    continue
                logger.warning(f"Login form not found at {page.url}")
                if self._is_logged_in(page.url):
                    return True
                logger.error("Cannot proceed: login form not found and not logged in")
                return False

        await asyncio.sleep(random.uniform(0.5, 1.0))

        try:
            await page.fill('input[name="session_key"]', "")
            await page.type('input[name="session_key"]', email, delay=80)
            await asyncio.sleep(random.uniform(0.3, 0.7))
            await page.fill('input[name="session_password"]', "")
            await page.type('input[name="session_password"]', password, delay=80)
            await asyncio.sleep(random.uniform(0.3, 0.7))
            await page.click('button[type="submit"]')
        except Exception as e:
            logger.error(f"Login form interaction failed: {e}")
            return False

        for _ in range(20):
            await asyncio.sleep(1)
            current_url = page.url
            if self._is_logged_in(current_url):
                logger.info(f"Login successful — at: {current_url}")
                return True
            if "checkpoint" in current_url or "challenge" in current_url or "verification" in current_url:
                break
            if "login" not in current_url and "login-submit" not in current_url:
                await asyncio.sleep(2)
                if self._is_logged_in(page.url):
                    logger.info(f"Login successful — at: {page.url}")
                    return True

        current_url = page.url
        if self._is_logged_in(current_url):
            logger.info(f"Login successful — at: {current_url}")
            return True

        if "checkpoint" in current_url or "challenge" in current_url or "verification" in current_url or "login-submit" in current_url:
            logger.warning(
                "LinkedIn verification challenge detected. "
                "Complete the verification in the browser window. "
                "Waiting up to 120 seconds..."
            )
            try:
                import os as _os
                _os.makedirs("logs", exist_ok=True)
                await page.screenshot(path="logs/login_challenge.png", full_page=True)
                logger.info("Screenshot saved to logs/login_challenge.png")
            except Exception as _e:
                logger.debug(f"Screenshot failed: {_e}")

            for elapsed in range(1, 41):
                await asyncio.sleep(3)
                current_url = page.url
                if self._is_logged_in(current_url):
                    logger.info(f"Verification completed — at: {current_url}")
                    return True
                logger.info(f"  Waiting for verification... ({elapsed * 3}s / 120s) | {current_url}")

            logger.error("Verification not completed within 120 seconds")
            return False

        logger.error(f"Login failed. Final URL: {page.url}")
        return False

    def _is_logged_in(self, url: str) -> bool:
        logged_in_paths = ["/feed", "/mynetwork", "/jobs", "/messaging", "/notifications", "/in/"]
        return any(p in url for p in logged_in_paths) and "login" not in url

    async def _scroll_and_collect_profile(
        self, page: Page, keyword: str, max_posts: int, pause_ms: int
    ) -> list[dict]:
        """Scroll loop for profile activity pages (uses role=article containers)."""
        posts_data: list[dict] = []
        seen_keys: set[str] = set()
        stall_count = 0
        last_count = 0

        while len(posts_data) < max_posts and stall_count < 4:
            batch = await _extract_profile_posts_js(page, keyword)

            for item in batch:
                if len(posts_data) >= max_posts:
                    break
                dedup_key = (
                    item.get("post_url")
                    or f"{item.get('author')}::{item.get('post_snippet', '')[:60]}"
                )
                if dedup_key and dedup_key not in seen_keys:
                    seen_keys.add(dedup_key)
                    posts_data.append(item)

            if len(posts_data) == last_count:
                stall_count += 1
                logger.debug(f"Profile scroll stall {stall_count}/4 — {len(posts_data)} posts")
            else:
                stall_count = 0

            last_count = len(posts_data)

            if len(posts_data) >= max_posts:
                break

            # Profile activity page scroll container
            await page.evaluate("""
                const ws = document.querySelector('main') || document.querySelector('.scaffold-layout__main');
                if (ws) ws.scrollTop += 1200;
                else window.scrollTo(0, document.body.scrollHeight);
            """)
            await asyncio.sleep(pause_ms / 1000.0 + random.uniform(0.3, 0.8))

            try:
                btn = await page.query_selector("button.scaffold-finite-scroll__load-button")
                if btn:
                    await btn.click()
                    await asyncio.sleep(1.5)
            except Exception:
                pass

        return posts_data

    async def _scroll_and_collect(
        self, page: Page, keyword: str, max_posts: int, pause_ms: int
    ) -> list[dict]:
        """Shared scroll loop used by keyword search scraping."""
        posts_data: list[dict] = []
        seen_keys: set[str] = set()
        stall_count = 0
        last_count = 0

        while len(posts_data) < max_posts and stall_count < 4:
            batch = await _extract_all_posts_js(page, keyword)

            for item in batch:
                if len(posts_data) >= max_posts:
                    break
                dedup_key = (
                    item.get("post_url")
                    or f"{item.get('author')}::{item.get('post_snippet', '')[:60]}"
                )
                if dedup_key and dedup_key not in seen_keys:
                    seen_keys.add(dedup_key)
                    posts_data.append(item)

            if len(posts_data) == last_count:
                stall_count += 1
                logger.debug(f"Scroll stall {stall_count}/4 — {len(posts_data)} posts")
            else:
                stall_count = 0

            last_count = len(posts_data)

            if len(posts_data) >= max_posts:
                break

            await page.evaluate("""
                const ws = document.querySelector('main#workspace');
                if (ws) ws.scrollTop += 1200;
                else window.scrollTo(0, document.body.scrollHeight);
            """)
            await asyncio.sleep(pause_ms / 1000.0 + random.uniform(0.3, 0.8))

            try:
                btn = await page.query_selector("button.scaffold-finite-scroll__load-button")
                if btn:
                    await btn.click()
                    await asyncio.sleep(1.5)
            except Exception:
                pass

        return posts_data

    async def scrape_keyword(self, keyword: str) -> list[dict]:
        page = self._page
        max_posts = self._config.scraping.max_posts_per_keyword
        pause_ms = self._config.scraping.scroll_pause_ms

        encoded = urllib.parse.quote(keyword)
        url = SEARCH_URL.format(keyword=encoded)

        logger.info(f"Navigating to search results for: {keyword}")
        await page.goto(url, wait_until="domcontentloaded")
        await asyncio.sleep(2 + random.uniform(0.5, 1.5))

        current_url = page.url
        if "login" in current_url:
            logger.error("Redirected to login — session may have expired")
            raise RuntimeError("LinkedIn session expired during scrape")

        if "limit" in (await page.title()).lower():
            logger.warning("LinkedIn rate limit page detected. Stopping this keyword.")
            return []

        posts_data = await self._scroll_and_collect(page, keyword, max_posts, pause_ms)

        # Best-effort: enrich posts that only have a profile URL (no real post link).
        # Uses the "Copy link to post" clipboard approach.
        posts_data = await self._enrich_post_urls(posts_data)

        logger.info(f"Collected {len(posts_data)} raw posts for keyword: {keyword}")
        return posts_data

    async def scrape_profile(self, profile_id: str, keyword_label: str = "") -> list[dict]:
        """Scrape recent posts from a LinkedIn profile's activity page."""
        page = self._page
        max_posts = self._config.scraping.max_posts_per_keyword
        pause_ms = self._config.scraping.scroll_pause_ms
        label = keyword_label or f"profile:{profile_id}"

        # /recent-activity/all/ shows all post types; /shares/ only shows original posts
        url = f"https://www.linkedin.com/in/{profile_id}/recent-activity/all/"
        logger.info(f"Scraping profile activity: {profile_id}")
        await page.goto(url, wait_until="domcontentloaded")
        await asyncio.sleep(2 + random.uniform(0.5, 1.5))

        current_url = page.url
        if "login" in current_url:
            logger.error(f"Redirected to login while scraping profile {profile_id}")
            return []

        if "404" in current_url or "unavailable" in current_url:
            logger.warning(f"Profile not accessible: {profile_id}")
            return []

        # Profile pages use role=article containers with a different text selector
        posts_data = await self._scroll_and_collect_profile(page, label, max_posts, pause_ms)
        logger.info(f"Collected {len(posts_data)} posts from profile: {profile_id}")
        return posts_data

    async def _enrich_post_urls(self, posts_data: list[dict]) -> list[dict]:
        """
        For posts where post_url is only an author profile URL (no real post link),
        attempt to capture the real post URL via the 'Copy link to post' menu option.
        This uses the clipboard intercept injected at browser context init.
        Best-effort — failures are silently skipped.
        """
        page = self._page
        needs_enrichment = [
            i for i, p in enumerate(posts_data)
            if p.get("post_url") and "/in/" in p.get("post_url", "")
            and "/posts/" not in p.get("post_url", "")
            and "/feed/update/" not in p.get("post_url", "")
        ]

        if not needs_enrichment:
            return posts_data

        logger.info(f"Enriching URLs for {len(needs_enrichment)} posts via clipboard...")

        # Find all control-menu buttons on the current page
        try:
            ctrl_btns = await page.query_selector_all('[aria-label*="Open control menu for post"]')
        except Exception:
            return posts_data

        for idx, btn in enumerate(ctrl_btns):
            if idx >= len(posts_data):
                break
            post = posts_data[idx]
            # Only enrich if this post needs it
            post_url = post.get("post_url", "")
            if "/posts/" in post_url or "/feed/update/" in post_url:
                continue

            try:
                # Reset clipboard capture
                await page.evaluate("window.__clipboardCapture = null;")

                # Click "..." menu
                await btn.click()
                await asyncio.sleep(0.6 + random.uniform(0.1, 0.3))

                # Find "Copy link to post" menu item
                copy_btn = await page.query_selector(
                    '[aria-label*="Copy link to post"], '
                    'button:has-text("Copy link to post"), '
                    'div[role="button"]:has-text("Copy link to post")'
                )
                if not copy_btn:
                    # Close menu with Escape
                    await page.keyboard.press("Escape")
                    await asyncio.sleep(0.3)
                    continue

                await copy_btn.click()
                await asyncio.sleep(0.5)

                # Read captured clipboard value
                captured = await page.evaluate("window.__clipboardCapture")
                if captured and "linkedin.com/posts/" in captured:
                    # Strip UTM params
                    clean_url = captured.split("?")[0]
                    posts_data[idx]["post_url"] = clean_url
                    logger.debug(f"Enriched URL: {clean_url}")
                else:
                    await page.keyboard.press("Escape")
                    await asyncio.sleep(0.3)

            except Exception as e:
                logger.debug(f"URL enrichment failed for post {idx}: {e}")
                try:
                    await page.keyboard.press("Escape")
                    await asyncio.sleep(0.2)
                except Exception:
                    pass

        return posts_data
