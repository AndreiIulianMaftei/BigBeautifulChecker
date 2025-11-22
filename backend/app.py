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

try:
    from src.get_bbox import get_bbox
    from src.price_calculator import analyze_damages_for_endpoint
except ImportError:
    import sys
    sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))
    from src.get_bbox import get_bbox
    from src.price_calculator import analyze_damages_for_endpoint

# Pydantic models for request/response
class DamageItem(BaseModel):
    item: str
    severity: int  # 1-5

class PriceRequest(BaseModel):
    damage_items: List[DamageItem]
    use_mock: bool = False
    max_concurrent: int = 5

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

        result_json = get_bbox(temp_input_path, destination_path, class_list)

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
        detection_result = get_bbox(temp_input_path, destination_path, class_list)
        
        # Transform detection output to price calculator input
        damage_items = []
        if detection_result and "annotation" in detection_result:
            for ann in detection_result["annotation"]:
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
                
                damage_items.append({
                    "item": item_name,
                    "severity": severity
                })
        
        # Calculate prices if damages were detected
        pricing_result = None
        if damage_items:
            pricing_result = await analyze_damages_for_endpoint(
                damage_items=damage_items,
                use_mock=use_mock_pricing,
                max_concurrent=max_concurrent
            )

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

def generate_cost_graph(pricing_result):
    analyses = pricing_result.get("analyses") if pricing_result else None
    if not analyses:
        return None

    years = list(range(1, 16))
    fig, ax = plt.subplots(figsize=(6, 4))

    for analysis in analyses:
        yearly_costs = analysis.get("ten_year_projection", {}).get("yearly_costs", [])
        cumulative = []
        running_total = 0
        cost_lookup = {
            int(item.get("year", 0)): float(item.get("cost", 0))
            for item in yearly_costs
            if item.get("year") is not None
        }
        for year in years:
            running_total += cost_lookup.get(year, 0)
            cumulative.append(running_total)
        ax.plot(years, cumulative, label=analysis.get("damage_item", "Damage"), linewidth=2)

    ax.set_xlabel("Year")
    ax.set_ylabel("Cumulative cost (CHF)")
    ax.set_title("15-year cost projection")
    ax.grid(True, alpha=0.3)
    ax.legend(fontsize=8)
    fig.tight_layout()

    buffer = io.BytesIO()
    fig.savefig(buffer, format="png")
    plt.close(fig)
    buffer.seek(0)
    return base64.b64encode(buffer.read()).decode("utf-8")


if __name__ == "__main__":
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
