# Lead Finder (Google Maps scraper)

Flask app that scrapes Google Maps with Playwright (Chromium) and exports results to CSV or Excel.
No API key needed.

## Setup (Python 3.11.9)

```bash
python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # macOS/Linux
pip install -r requirements.txt
playwright install chromium
python app.py
```

Open http://127.0.0.1:5000

## How it works

1. `scraper.py` opens `google.com/maps/search/<type> in <location>`, scrolls the results list and collects place links.
2. It then opens each place page and reads name, category, address, phone, website, rating, reviews, status and coordinates.
3. `app.py` runs this as a background job; the page polls for progress and shows rows as they arrive. You can press Stop and keep what was collected.

## Troubleshooting

- **Nothing loads / CAPTCHA:** run with the browser visible to see what happens:
  `set HEADLESS=false` (Windows cmd) or `HEADLESS=false python app.py` (macOS/Linux), then `python app.py`.
- **A field comes back empty for every place:** Google changed its markup. Update the selectors in
  `scraper.py` (`FEED`, `PLACE_LINK`, `EXTRACT_JS`).
- Expect roughly 3-5 seconds per business. Keep result counts modest and avoid rapid repeated runs
  to reduce the chance of being blocked.
- Emails are not shown on Google Maps, so they are not collected.

## Important

Scraping Google Maps is against Google's Terms of Service and can get your IP temporarily blocked.
Use it for low-volume, personal research, and follow applicable data-protection and
anti-spam laws when contacting businesses. The official Places API is the compliant option.

## Deploying on Render

Chromium needs system libraries, so use **Docker**, not the native Python runtime:

1. Push this folder to GitHub.
2. Render → New → Web Service → connect the repo → **Language: Docker** (it finds the `Dockerfile`).
3. Choose an instance with at least 1-2 GB RAM (Chromium often crashes on 512 MB).
4. Deploy. No environment variables are required.

If you must use the native Python runtime instead, set `PYTHON_VERSION=3.11.9`
(the `.python-version` file does this too); Chromium will still fail to launch there
because system libraries cannot be installed.

Note: Google often shows CAPTCHAs to cloud/datacenter IPs, so scraping may work
locally but fail on a server.
