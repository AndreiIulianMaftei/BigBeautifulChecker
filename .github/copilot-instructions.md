# Copilot / Agent Instructions — BigBeautifulChecker

Short, actionable guidance for AI coding agents working on this repo.

Big picture
- FastAPI backend in `backend/app.py` is the single HTTP surface that orchestrates three subsystems:
  - Image damage detection (`backend/src/get_bbox.py`) using an LLM+image input pipeline.
  - Repair cost estimation (`backend/src/price_calculator.py`) that reads a damage CSV and calls an LLM to fill gaps.
  - Property valuation (`backend/src/property_valuation.py`) which queries ThinkImmo.
  - Property listing scraper (`backend/src/immo24_scraper.py`) for fetching images/data from German property sites.
- The canonical damage/component CSV is `dataset/message.csv` (used by `get_bbox.py` and `price_calculator.py`).

Runtime & env vars
- Install dependencies: `pip install -r backend/requirements.txt`.
- Required env vars:
  - `GEMINI_API_KEY` — key for `google.generativeai` (Gemini) calls.
  - `model` — model id used by `genai.GenerativeModel(os.getenv("model"))` in detection code.
- Required for scraping: Playwright with Chromium. Run `playwright install chromium` after pip install.

How to run locally
- Create a virtualenv, install, set env vars (or `.env`), then:
  ```bash
  uvicorn backend.app:app --reload --port 8000
  ```

Important implementation patterns (follow these)
- LLM outputs are expected to be machine-readable JSON only. Prompts frequently end with explicit: "Return ONLY a valid JSON object/array" — do not add extra prose.
- Bounding-box format from detection: `box_2d` is [ymin, xmin, ymax, xmax] normalized to a 0–1000 range. Code converts to pixel coords in `get_bbox.py`.
- Severity is an integer 1–5 (1 cosmetic → 5 critical). Price workflows clamp severity to 1–5.
- Pricing functions support `use_mock=True` to avoid API quota during development/tests.
- Concurrency: `analyze_damages_for_endpoint` uses `asyncio.Semaphore(max_concurrent)` to limit concurrent LLM calls — preserve this pattern when introducing parallel work.

Property scraper notes (immo24_scraper.py)
- Supports two German property websites:
  - **immowelt.de** — RECOMMENDED, works reliably with Playwright (no bot blocking)
  - **immobilienscout24.de** — Has strong Imperva bot protection, will return `bot_detected: true`
- Playwright is required (not optional) for Immowelt since it uses JS-rendered content
- Headless mode often fails; the scraper automatically falls back to visible browser mode
- Cookie consent is handled automatically via `_accept_cookie_consent()`
- Both single listings (`/expose/...`) and search pages (`/suche/...`) are supported

Where to look for examples
- Endpoint orchestration: `backend/app.py` (see /detect, /calculate-price, /detect-and-price, /immo24/scrape).
- Detection prompts & parsing: `backend/src/get_bbox.py` (category prompt, detection prompt, JSON parsing).
- Pricing orchestration and example response format: `backend/src/price_calculator.py` (look for `analyze_damages_for_endpoint` and the `if __name__ == "__main__"` example run).
- Scraping: `backend/src/immo24_scraper.py` — `fetch_immo24_listing()` is the main entry point, routes to Immowelt or ImmoScout24 handlers based on URL.

Editing guidance for agents
- When changing prompts: keep the exact JSON schema and post-processing code in sync. If you change the expected JSON keys, update both the prompt and the consumer code (e.g., `get_bbox.py` parsing and `app.py` callers).
- If you add new env vars or secrets, document them here and prefer `.env` in `backend/` for local dev.
- Keep external network calls behind `use_mock` toggles where present to enable offline tests.
- For scraper changes: test with both single listings and search pages; ensure `_dedupe_preserve_order()` always returns a list (not None).

If anything in this file is unclear, tell me which endpoint, file, or behavior you want clarified and I will expand the instructions or add examples.
