"""
Google Maps scraper (Playwright + Chromium).

Flow:
  1. Open the Maps search page and scroll the results feed to collect place links.
  2. Open each place page and read name, category, address, phone, website,
     rating, review count, status and coordinates.

NOTE: Google Maps' HTML changes often. All selectors live in this file
(see FEED, PLACE_LINK and EXTRACT_JS) so they are easy to update if a field
stops being collected. Set the environment variable HEADLESS=false to watch
the browser while debugging.
"""

import os
import random
import re
from urllib.parse import quote_plus

HEADLESS = os.getenv("HEADLESS", "true").lower() != "false"

FEED = 'div[role="feed"]'
PLACE_LINK = 'a[href*="/maps/place/"]'
INFO_READY = 'button[data-item-id="address"]'

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# Runs inside the place page. Each field has fallbacks because class names
# on Google Maps are obfuscated and change from time to time.
EXTRACT_JS = r"""
(fallbackName) => {
  const q = (s) => document.querySelector(s);
  const txt = (el) => (el ? (el.textContent || "").trim() : "");
  const attr = (el, a) => (el ? (el.getAttribute(a) || "") : "");
  const main = q('div[role="main"]') || document.body;

  const name = txt(q('h1.DUwDvf')) || txt(q('h1.fontHeadlineLarge')) || fallbackName;

  const addrBtn = q('button[data-item-id="address"]');
  const address = attr(addrBtn, 'aria-label').replace(/^\s*Address:\s*/i, '').trim() || txt(addrBtn);

  const phoneBtn = q('button[data-item-id^="phone:tel:"]');
  const phone = attr(phoneBtn, 'aria-label').replace(/^\s*Phone:\s*/i, '').trim()
    || attr(phoneBtn, 'data-item-id').replace('phone:tel:', '');

  const site = q('a[data-item-id="authority"]');
  const website = site ? site.href : '';

  let rating = '';
  const ratingEl = q('div.F7nice span[aria-hidden="true"]');
  if (ratingEl) rating = txt(ratingEl);
  if (!rating) {
    const m = attr(q('span[role="img"][aria-label*="star"]'), 'aria-label').match(/[\d.]+/);
    if (m) rating = m[0];
  }

  let reviews = '';
  const revEl = q('div.F7nice span[aria-label*="review"]') || q('button[aria-label*="review"]');
  const rm = attr(revEl, 'aria-label').match(/[\d,]+/);
  if (rm) reviews = rm[0].replace(/,/g, '');

  const category = txt(q('button.DkEOxe')) || txt(q('button[jsaction*="category"]'));

  const head = (main.innerText || '').slice(0, 2000);
  let status = 'Operational';
  if (/permanently closed/i.test(head)) status = 'Permanently Closed';
  else if (/temporarily closed/i.test(head)) status = 'Temporarily Closed';

  return { name, address, phone, website, rating, reviews, category, status };
}
"""


class ScrapeError(Exception):
    """Raised for problems the user should see (CAPTCHA, missing browser, ...)."""


def _coords(*urls):
    for url in urls:
        m = re.search(r"!3d(-?\d+\.\d+)!4d(-?\d+\.\d+)", url) or re.search(
            r"@(-?\d+\.\d+),(-?\d+\.\d+)", url
        )
        if m:
            return float(m.group(1)), float(m.group(2))
    return "", ""


def _to_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return ""


def _to_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return ""


def _handle_consent(page, timeout_error):
    """Click through Google's cookie consent page if it appears (EU/UK etc.)."""
    if "consent.google" not in page.url:
        return
    for label in ("Accept all", "Reject all", "I agree"):
        button = page.get_by_role("button", name=re.compile(label, re.I))
        if button.count():
            button.first.click()
            break
    try:
        page.wait_for_url(re.compile(r"google\.[^/]+/maps"), timeout=15000)
    except timeout_error:
        pass


def _collect_links(page, query, max_results, on_progress, should_cancel, timeout_error):
    url = f"https://www.google.com/maps/search/{quote_plus(query)}?hl=en"
    page.goto(url, wait_until="domcontentloaded", timeout=45000)
    _handle_consent(page, timeout_error)

    try:
        page.wait_for_selector(FEED, timeout=20000)
    except timeout_error:
        # A very specific query can jump straight to a single place page.
        if "/maps/place/" in page.url:
            return [{"href": page.url, "name": ""}]
        raise ScrapeError(
            "No results list appeared. Google may have shown a CAPTCHA, blocked "
            "the request, or changed its layout. Try again later, or run with "
            "HEADLESS=false to see what the browser sees."
        )

    seen = {}
    stale_rounds = 0
    while len(seen) < max_results and stale_rounds < 6:
        if should_cancel():
            break

        anchors = page.eval_on_selector_all(
            f"{FEED} {PLACE_LINK}",
            "els => els.map(e => [e.href, e.getAttribute('aria-label') || ''])",
        )
        before = len(seen)
        for href, name in anchors:
            seen.setdefault(href.split("?")[0], {"href": href, "name": name})
        on_progress(f"Loading listings… {min(len(seen), max_results)} found")

        if len(seen) >= max_results:
            break
        if page.get_by_text(re.compile(r"reached the end of the list")).count():
            break

        stale_rounds = stale_rounds + 1 if len(seen) == before else 0
        page.eval_on_selector(FEED, "el => el.scrollTo(0, el.scrollHeight)")
        page.wait_for_timeout(1500)

    return list(seen.values())[:max_results]


def _scrape_place(page, link, timeout_error):
    page.goto(link["href"], wait_until="domcontentloaded", timeout=45000)
    try:
        page.wait_for_selector(
            f'{INFO_READY}, h1.DUwDvf, h1.fontHeadlineLarge', timeout=12000
        )
        # Some places have no address button; give the panel a moment anyway.
        page.wait_for_timeout(600)
    except timeout_error:
        pass

    data = page.evaluate(EXTRACT_JS, link.get("name", ""))
    lat, lng = _coords(link["href"], page.url)

    return {
        "id": link["href"].split("?")[0],
        "name": data["name"],
        "category": data["category"],
        "address": data["address"],
        "phone": data["phone"],
        "website": data["website"],
        "rating": _to_float(data["rating"]),
        "reviews": _to_int(data["reviews"]),
        "status": data["status"],
        "maps_url": link["href"],
        "latitude": lat,
        "longitude": lng,
    }


def scrape(keyword, location, max_results, on_progress, should_cancel):
    """
    Scrape Google Maps for "<keyword> in <location>".

    on_progress(message, results=None) is called as work advances.
    should_cancel() returns True when the user pressed Stop.
    Returns the list of result dicts collected.
    """
    try:
        from playwright.sync_api import Error as PWError
        from playwright.sync_api import TimeoutError as PWTimeout
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise ScrapeError(
            "Playwright is not installed. Run: pip install -r requirements.txt "
            "and then: playwright install chromium"
        )

    results = []
    query = f"{keyword} in {location}"

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(
                headless=HEADLESS,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                ],
            )
        except Exception as exc:
            raise ScrapeError(
                f"Could not start Chromium ({exc}). Run: playwright install chromium"
            )

        try:
            context = browser.new_context(
                locale="en-US",
                user_agent=USER_AGENT,
                viewport={"width": 1366, "height": 900},
            )
            # Skip images/media/fonts: we only need the text, and it's much faster.
            context.route(
                "**/*",
                lambda route: route.abort()
                if route.request.resource_type in ("image", "media", "font")
                else route.continue_(),
            )

            list_page = context.new_page()
            on_progress("Opening Google Maps…")
            links = _collect_links(
                list_page, query, max_results, on_progress, should_cancel, PWTimeout
            )
            list_page.close()

            detail_page = context.new_page()
            total = len(links)
            for i, link in enumerate(links, start=1):
                if should_cancel():
                    break
                on_progress(f"Reading details {i}/{total}…", results)

                row = None
                for _attempt in range(2):  # one retry per place
                    try:
                        row = _scrape_place(detail_page, link, PWTimeout)
                        break
                    except PWTimeout:
                        continue
                if row and row["name"]:
                    results.append(row)

                on_progress(f"Reading details {i}/{total}…", results)
                detail_page.wait_for_timeout(random.randint(500, 1300))
        except PWError as exc:
            first_line = str(exc).strip().splitlines()[0] if str(exc).strip() else "unknown"
            raise ScrapeError(
                f"Browser error: {first_line}. Check your internet connection and try again."
            )
        finally:
            browser.close()

    on_progress("Done", results)
    return results
