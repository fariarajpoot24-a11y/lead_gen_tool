"""
Lead Generation Tool
Flask backend that scrapes Google Maps (via Playwright) in a background job
and exports the results as CSV or Excel (.xlsx).
"""

import csv
import io
import threading
import time
import uuid
from datetime import datetime

from flask import Flask, jsonify, render_template, request, send_file
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from scraper import ScrapeError, scrape

app = Flask(__name__)

MAX_RESULTS_CAP = 120

# Column definitions shared by CSV and Excel exports: (key, header)
COLUMNS = [
    ("name", "Business Name"),
    ("category", "Category"),
    ("address", "Address"),
    ("phone", "Phone"),
    ("website", "Website"),
    ("rating", "Rating"),
    ("reviews", "Reviews"),
    ("status", "Status"),
    ("maps_url", "Google Maps URL"),
    ("latitude", "Latitude"),
    ("longitude", "Longitude"),
]

# In-memory job store (fine for a single-user local tool).
JOBS = {}
JOBS_LOCK = threading.Lock()


# --------------------------------------------------------------------------- #
# Background scraping jobs
# --------------------------------------------------------------------------- #
def _run_job(job_id, keyword, location, max_results):
    job = JOBS[job_id]

    def on_progress(message, results=None):
        job["message"] = message
        if results is not None:
            job["results"] = list(results)

    try:
        scrape(keyword, location, max_results, on_progress, lambda: job["cancel"])
        job["state"] = "cancelled" if job["cancel"] else "done"
    except ScrapeError as exc:
        job["state"], job["error"] = "error", str(exc)
    except Exception as exc:  # keep the UI informed instead of hanging
        job["state"], job["error"] = "error", f"Unexpected error: {exc}"
    finally:
        job["finished"] = time.time()


def _purge_old_jobs():
    cutoff = time.time() - 3600
    for job_id in [
        j for j, v in JOBS.items() if v.get("finished") and v["finished"] < cutoff
    ]:
        JOBS.pop(job_id, None)


@app.post("/api/search")
def start_search():
    data = request.get_json(silent=True) or {}
    keyword = (data.get("keyword") or "").strip()
    location = (data.get("location") or "").strip()
    if not keyword or not location:
        return jsonify(error="Enter both a business type and a location."), 400

    try:
        max_results = int(data.get("max_results", 20))
    except (TypeError, ValueError):
        max_results = 20
    max_results = max(1, min(max_results, MAX_RESULTS_CAP))

    with JOBS_LOCK:
        _purge_old_jobs()
        if any(j["state"] == "running" for j in JOBS.values()):
            return jsonify(error="A search is already running. Wait or stop it first."), 409

        job_id = uuid.uuid4().hex
        JOBS[job_id] = {
            "state": "running",
            "message": "Starting browser…",
            "results": [],
            "target": max_results,
            "error": "",
            "cancel": False,
            "finished": None,
        }

    threading.Thread(
        target=_run_job, args=(job_id, keyword, location, max_results), daemon=True
    ).start()
    return jsonify(job_id=job_id)


@app.get("/api/status/<job_id>")
def job_status(job_id):
    job = JOBS.get(job_id)
    if not job:
        return jsonify(error="Unknown search."), 404
    return jsonify(
        state=job["state"],
        message=job["message"],
        error=job["error"],
        target=job["target"],
        count=len(job["results"]),
        results=job["results"],
    )


@app.post("/api/cancel/<job_id>")
def cancel_job(job_id):
    job = JOBS.get(job_id)
    if not job:
        return jsonify(error="Unknown search."), 404
    job["cancel"] = True
    job["message"] = "Stopping…"
    return jsonify(ok=True)


# --------------------------------------------------------------------------- #
# Export helpers
# --------------------------------------------------------------------------- #
def safe_cell(value):
    """Neutralise spreadsheet formula injection (=, +, -, @ at cell start)."""
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + value
    return value


def timestamped(name, ext):
    return f"{name}_{datetime.now():%Y%m%d_%H%M%S}.{ext}"


def _rows_from_request():
    data = request.get_json(silent=True) or {}
    rows = data.get("results")
    if not isinstance(rows, list) or not rows:
        return None
    return [r for r in rows if isinstance(r, dict)]


@app.post("/api/export/csv")
def export_csv():
    rows = _rows_from_request()
    if rows is None:
        return jsonify(error="No results to export."), 400

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([header for _, header in COLUMNS])
    for row in rows:
        writer.writerow([safe_cell(row.get(key, "")) for key, _ in COLUMNS])

    # utf-8-sig adds a BOM so Excel opens non-ASCII names correctly.
    output = io.BytesIO(buffer.getvalue().encode("utf-8-sig"))
    return send_file(
        output,
        mimetype="text/csv",
        as_attachment=True,
        download_name=timestamped("leads", "csv"),
    )


@app.post("/api/export/xlsx")
def export_xlsx():
    rows = _rows_from_request()
    if rows is None:
        return jsonify(error="No results to export."), 400

    wb = Workbook()
    ws = wb.active
    ws.title = "Leads"

    ws.append([header for _, header in COLUMNS])
    for row in rows:
        ws.append([safe_cell(row.get(key, "")) for key, _ in COLUMNS])

    header_fill = PatternFill("solid", fgColor="1F3A5F")
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = header_fill
        cell.alignment = Alignment(vertical="center")
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions

    for idx, (key, header) in enumerate(COLUMNS, start=1):
        longest = max([len(header)] + [len(str(r.get(key, ""))) for r in rows])
        ws.column_dimensions[get_column_letter(idx)].width = min(longest + 2, 60)

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    return send_file(
        output,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name=timestamped("leads", "xlsx"),
    )


@app.get("/")
def index():
    return render_template("index.html")


if __name__ == "__main__":
    # No debug reloader: it would kill a running scrape whenever a file changes.
    app.run(port=5000, threaded=True)
