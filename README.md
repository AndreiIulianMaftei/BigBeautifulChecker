# Crib Checker

**AI-powered property damage detection and repair cost estimation for real estate.**

Crib Checker analyzes property images to detect damages, estimate repair costs, and provide property valuation insights — helping buyers make informed decisions.

## Live Demo

**Try it now:** [https://crib-checker-production.up.railway.app/](https://crib-checker-production.up.railway.app/)

---

## Features

- **Damage Detection** — Uses AI (Gemini) to identify damages in property images with bounding boxes and severity ratings (1-5)
- **Repair Cost Estimation** — Calculates estimated repair costs based on detected damages
- **Property Valuation** — Provides market insights and price projections
- **Property Scraping** — Fetches images, price, and location from German property listings (Immowelt recommended)
- **Dashboard Metrics** — Visual breakdown of damages, costs, and investment projections
- **Price Updates** — Real-time mortgage/price data powered by Interhyp API

---

## How to Test

1. **Go to the demo:** [https://crib-checker-production.up.railway.app/](https://crib-checker-production.up.railway.app/)

2. **Option A — Use a property link (recommended):**
   - Paste an **Immowelt** link (preferred, as it allows data collection)
   - The app will auto-fetch up to 5 images, price, and location
   - If price or location detection fails, enter them manually

3. **Option B — Upload your own images:**
   - Click "Upload Images" to select photos
   - On mobile, you can also select "Camera" to take photos directly

4. **Important:** Processing won't start until both **location** and **price** are provided

5. **Wait for analysis** — This takes a moment, grab a coffee

6. **View Results:**
   - The dashboard displays detailed damage metrics
   - See repair cost breakdowns and severity ratings
   - View investment projections and property insights
   - Price updates at the bottom are powered by the **Interhyp API**

---

## Run Locally

### Prerequisites

- Python 3.10+
- A Gemini API key

### Setup

1. **Clone the repository:**
   ```bash
   git clone https://github.com/AndreiIulianMaftei/BigBeautifulChecker.git
   cd BigBeautifulChecker
   ```

2. **Create and activate a virtual environment:**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r backend/requirements.txt
   ```

4. **Install Playwright for property scraping:**
   ```bash
   playwright install chromium
   ```

5. **Configure environment variables:**
   
   Create a `.env` file in `backend/` with:
   ```env
   GEMINI_API_KEY=your_gemini_api_key_here
   model=gemini-2.5-flash
   ```

6. **Run the server:**
   ```bash
   uvicorn backend.app:app --reload --port 8000
   ```

7. **Open in browser:** [http://localhost:8000](http://localhost:8000)

---

## Project Structure

```
├── backend/
│   ├── app.py                 # FastAPI application
│   ├── requirements.txt       # Python dependencies
│   └── src/
│       ├── get_bbox.py        # Damage detection with AI
│       ├── price_calculator.py # Repair cost estimation
│       ├── property_valuation.py # Property market insights
│       └── immo24_scraper.py  # Property listing scraper
├── dataset/
│   └── message.csv            # Damage/component pricing data
├── website/                   # React frontend
└── sample_images/             # Test images
```

---

## Environment Variables

| Variable | Description |
|----------|-------------|
| `GEMINI_API_KEY` | Your Google Gemini API key |
| `model` | Gemini model ID (e.g., `gemini-2.5-flash`) |

---

## License

MIT License

---

**Built with ❤️ for smarter property investments**