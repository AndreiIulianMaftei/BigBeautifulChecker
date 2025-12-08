import os
import shutil
import uvicorn
import json
import asyncio
import base64
import io
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Optional
from pydantic import BaseModel
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

try:
    from src.get_bbox import get_bbox
    from src.immo24_scraper import fetch_immo24_listing
    from src.price_calculator import analyze_damages_for_endpoint
    from src.property_valuation import calculate_property_valuation_endpoint
except ImportError:
    import sys
    sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))
    from src.get_bbox import get_bbox
    from src.immo24_scraper import fetch_immo24_listing
    from src.price_calculator import analyze_damages_for_endpoint
    from src.property_valuation import calculate_property_valuation_endpoint

# Pydantic models for request/response
class DamageItem(BaseModel):
    item: str
    severity: int  # 1-5
    existing_pricing: Optional[dict] = None  # Optional pre-calculated pricing to avoid LLM recalculation

class PriceRequest(BaseModel):
    damage_items: List[DamageItem]
    use_mock: bool = False
    max_concurrent: int = 5

class PropertyValuationRequest(BaseModel):
    current_price: float
    address: str
    property_type: str = "APARTMENTBUY"

class CombinedValuationRequest(PropertyValuationRequest):
    damage_items: List[DamageItem] = []
    use_mock: bool = False
    max_concurrent: int = 5

class Immo24LinkRequest(BaseModel):
    url: str
    max_images: int = 5

app = FastAPI(title="Damage Detection Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOAD_DIR = "temp_uploads"
RESULTS_DIR = "temp_results"
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(RESULTS_DIR, exist_ok=True)

@app.post("/detect", summary="Detect damages in an uploaded image")
async def detect_damage(
    file: UploadFile = File(...),
    classes: Optional[str] = Form(
        "[]", 
        description="A JSON formatted string of classes, e.g., '[\"crack\", \"mold\"]'"
    )
):
    temp_input_path = None
    destination_path = None
    try:
        try:
            class_list = json.loads(classes)
            if not isinstance(class_list, list):
                raise ValueError("Classes must be a list")
        except (json.JSONDecodeError, ValueError):
            class_list = []

        temp_filename = f"{os.path.splitext(file.filename)[0]}_input{os.path.splitext(file.filename)[1]}"
        temp_input_path = os.path.join(UPLOAD_DIR, temp_filename)
        
        with open(temp_input_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        output_filename = f"{os.path.splitext(file.filename)[0]}_annotated.png"
        destination_path = os.path.join(RESULTS_DIR, output_filename)

        result_json = get_bbox(temp_input_path, destination_path)

        encoded_image = None
        if os.path.exists(destination_path):
            with open(destination_path, "rb") as annotated_file:
                encoded_image = base64.b64encode(annotated_file.read()).decode("utf-8")

        return {
            "result": result_json,
            "annotated_image_base64": encoded_image,
            "filename": output_filename,
        }

    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Internal Server Error: {str(e)}")
    
    finally:
        if temp_input_path and os.path.exists(temp_input_path):
            # os.remove(temp_input_path)
            pass

@app.post("/calculate-price", summary="Calculate repair costs for detected damages")
async def calculate_price(request: PriceRequest):
    """
    Calculate 10-year cost projections for detected damages.
    
    Request body:
    {
        "damage_items": [
            {"item": "Boiler", "severity": 5},
            {"item": "crack", "severity": 3}
        ],
        "use_mock": false,
        "max_concurrent": 5
    }
    """
    try:
        # Convert Pydantic models to dicts
        damage_items_list = [item.dict() for item in request.damage_items]
        
        # Call the price calculator
        result = await analyze_damages_for_endpoint(
            damage_items=damage_items_list,
            use_mock=request.use_mock,
            max_concurrent=request.max_concurrent
        )
        
        return result
    
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Price calculation error: {str(e)}")

@app.post("/detect-and-price", summary="Detect damages and calculate repair costs")
async def detect_and_price(
    file: UploadFile = File(...),
    classes: Optional[str] = Form(
        "[]", 
        description="A JSON formatted string of classes, e.g., '[\"crack\", \"mold\"]'"
    ),
    use_mock_pricing: bool = Form(False, description="Use mock data for pricing (for testing)"),
    max_concurrent: int = Form(5, description="Maximum concurrent API calls for pricing")
):
    """
    Combined endpoint: Detect damages in image and calculate repair costs.
    
    Returns both detection results and 10-year cost projections.
    """
    temp_input_path = None
    
    try:
        # Parse classes
        try:
            class_list = json.loads(classes)
            if not isinstance(class_list, list):
                raise ValueError("Classes must be a list")
        except (json.JSONDecodeError, ValueError):
            class_list = []

        # Save uploaded file
        temp_filename = f"{os.path.splitext(file.filename)[0]}_input{os.path.splitext(file.filename)[1]}"
        temp_input_path = os.path.join(UPLOAD_DIR, temp_filename)
        
        with open(temp_input_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        # Run detection
        output_filename = f"{os.path.splitext(file.filename)[0]}_annotated.png"
        destination_path = os.path.join(RESULTS_DIR, output_filename)
        detection_result = await asyncio.to_thread(get_bbox, temp_input_path, destination_path)
        
        # Transform detection output to price calculator input
        damage_items = []
        if detection_result and "annotation" in detection_result:
            print(f"DEBUG: Detection result has {len(detection_result['annotation'])} annotations")
            for ann in detection_result["annotation"]:
                print(f"DEBUG: Annotation: {ann}")
                # Extract severity (convert string to int if needed)
                severity = ann.get("severity", 3)
                if isinstance(severity, str):
                    try:
                        severity = int(severity)
                    except ValueError:
                        severity = 3  # default to medium severity
                
                # Clamp severity to 1-5 range
                severity = max(1, min(5, severity))
                
                # Use subcategory for pricing (this matches CSV Item/Subitem)
                # Fallback to label if subcategory not present
                item_name = ann.get("subcategory", ann.get("label", "unknown"))
                
                print(f"DEBUG: Creating damage_item - item: {item_name}, severity: {severity}")
                
                damage_items.append({
                    "item": item_name,
                    "severity": severity
                })
        
        print(f"DEBUG: Total damage_items: {len(damage_items)}")
        
        # Calculate prices if damages were detected
        # If no damages detected but detection ran, use mock data to show what pricing would look like
        pricing_result = None
        if damage_items:
            print(f"DEBUG: Calling analyze_damages_for_endpoint with {len(damage_items)} items")
            pricing_result = await analyze_damages_for_endpoint(
                damage_items=damage_items,
                use_mock=use_mock_pricing,
                max_concurrent=max_concurrent
            )
            print(f"DEBUG: Pricing result: {pricing_result is not None}")
            if pricing_result:
                print(f"DEBUG: Pricing has {len(pricing_result.get('analyses', []))} analyses")
        else:
            print("DEBUG: No damage_items found - Gemini detection returned empty")
            print("DEBUG: This usually means API quota exceeded or model refusal")
            print("DEBUG: Consider using use_mock_pricing=true for testing")

        encoded_image = None
        if os.path.exists(destination_path):
            with open(destination_path, "rb") as annotated_file:
                encoded_image = base64.b64encode(annotated_file.read()).decode("utf-8")

        graph_image = None
        if pricing_result:
            graph_image = generate_cost_graph(pricing_result)

        # Combine results
        combined_result = {
            "detection": detection_result,
            "pricing": pricing_result,
            "annotated_image_base64": encoded_image,
            "cost_graph_base64": graph_image,
            "filename": output_filename,
            "annotated_image_path": destination_path
        }
        
        return combined_result

    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Internal Server Error: {str(e)}")
    
    finally:
        if temp_input_path and os.path.exists(temp_input_path):
            # os.remove(temp_input_path)
            pass

@app.post("/immo24/scrape", summary="Extract listing details from a German property site")
def scrape_immo24_listing(request: Immo24LinkRequest):
    """
    Fetch price, address, and photos from a German property listing URL.
    
    **Supported Sites:**
    - **immowelt.de** (RECOMMENDED - reliable, no bot blocking)
    - **immobilienscout24.de** (may be blocked by bot detection)
    
    Uses Playwright (headless browser) to automatically handle cookie consent.
    Supports both individual listing URLs (/expose/...) and search result pages.
    
    **Example URLs:**
    - https://www.immowelt.de/expose/12345
    - https://www.immowelt.de/suche/muenchen/wohnungen/mieten
    - https://www.immobilienscout24.de/expose/123456789
    
    If ImmoScout24 is blocked, the response will include a 'bot_detected' flag
    with alternative options.
    """
    try:
        print(f"[DEBUG] Scraping URL: {request.url}, max_images: {request.max_images}")
        data = fetch_immo24_listing(request.url, max_images=request.max_images)
        print(f"[DEBUG] Got data type: {type(data)}")
        return data
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        import traceback
        print("[DEBUG] Full traceback:")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Unable to process listing: {str(e)}")

@app.post("/property-valuation", summary="Calculate 10-year property valuation")
def property_valuation(request: PropertyValuationRequest):
    """
    Calculate 10-year property valuation based on market gross return.
    
    Uses ThinkImmo API to fetch market data and calculate property appreciation
    and rental income projections over 10 years.
    
    Request body:
    {
        "current_price": 450000,
        "address": "Munich, Bavaria",
        "property_type": "APARTMENTBUY"
    }
    
    Property types:
    - APARTMENTBUY
    - HOUSEBUY
    - LANDBUY
    - GARAGEBUY
    - OFFICEBUY
    """
    try:
        result = calculate_property_valuation_endpoint(
            current_price=request.current_price,
            address=request.address,
            property_type=request.property_type
        )
        
        return result
    
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Property valuation error: {str(e)}")

@app.post("/valuation-report", summary="Combined property valuation and repair cost outlook")
async def valuation_report(request: CombinedValuationRequest):
    """Generate a combined property valuation and damage repair outlook."""
    try:
        valuation = property_valuation(PropertyValuationRequest(
            current_price=request.current_price,
            address=request.address,
            property_type=request.property_type
        ))

        repair_summary = None
        if request.damage_items:
            repair_summary = await calculate_price(PriceRequest(
                damage_items=request.damage_items,
                use_mock=request.use_mock,
                max_concurrent=request.max_concurrent
            ))

        combined = {
            "address": request.address,
            "current_price": request.current_price,
            "property_type": request.property_type,
            "valuation": valuation,
            "repairs": repair_summary,
        }

        if repair_summary and repair_summary.get("analyses"):
            # Access the correct nested structure
            total_repairs = repair_summary["summary"]["cost_breakdown"]["grand_total_10year_cost_EUR"]
            final_value = valuation["valuation"]["10_year_summary"]["final_property_value"]
            combined["insights"] = {
                "net_projected_value": round(final_value - total_repairs, 2),
                "repair_to_value_ratio": round((total_repairs / request.current_price) * 100, 2)
            }

        return combined

    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Valuation report error: {str(e)}")

def generate_cost_graph(pricing_result):
    analyses = pricing_result.get("analyses") if pricing_result else None
    if not analyses:
        return None

    years = list(range(1, 11))  # 1-10 years only
    key_years = [1, 5, 10]  # Important milestones
    fig, ax = plt.subplots(figsize=(6, 4))

    for analysis in analyses:
        yearly_costs = analysis.get("projection_10year", {}).get("yearly_costs", [])
        cumulative = []
        cost_lookup = {
            int(item.get("year", 0)): float(item.get("cumulative_cost", 0))
            for item in yearly_costs
            if item.get("year") is not None
        }
        for year in years:
            cumulative.append(cost_lookup.get(year, 0))
        
        line, = ax.plot(years, cumulative, label=analysis.get("damage_item", "Damage"), linewidth=2)
        
        # Highlight key years (1, 5, 10) with markers
        key_cumulative = [cost_lookup.get(y, 0) for y in key_years]
        ax.scatter(key_years, key_cumulative, color=line.get_color(), s=80, zorder=5, edgecolors='white', linewidths=1.5)

    # Add vertical lines at key years
    for ky in key_years:
        ax.axvline(x=ky, color='gray', linestyle='--', alpha=0.3)
    
    ax.set_xlabel("Year")
    ax.set_ylabel("Cumulative cost (EUR)")
    ax.set_title("10-Year Cost Projection")
    ax.set_xticks(years)
    ax.set_xlim(0.5, 10.5)
    ax.grid(True, alpha=0.3)
    ax.legend(fontsize=8)
    fig.tight_layout()

    buffer = io.BytesIO()
    fig.savefig(buffer, format="png")
    plt.close(fig)
    buffer.seek(0)
    return base64.b64encode(buffer.read()).decode("utf-8")


base_static_dir = os.path.join(os.path.dirname(__file__), "static")
nested_static_dir = os.path.join(base_static_dir, "static")

if os.path.exists(nested_static_dir):
    app.mount("/static", StaticFiles(directory=nested_static_dir), name="static")
elif os.path.exists(base_static_dir):
    app.mount("/static", StaticFiles(directory=base_static_dir), name="static")

@app.get("/{full_path:path}")
async def serve_react_app(full_path: str):
    file_path = os.path.join(base_static_dir, full_path)
    
    if os.path.exists(file_path) and os.path.isfile(file_path):
        return FileResponse(file_path)
    
    index_file = os.path.join(base_static_dir, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)
        
    return {"error": "Frontend files not found. Did you run npm run build?"}

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=False)
