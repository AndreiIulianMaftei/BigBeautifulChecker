import os
import shutil
import uvicorn
import json
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from typing import List, Optional

try:
    from src.get_bbox import get_bbox
except ImportError:
    import sys
    sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))
    from src.get_bbox import get_bbox

app = FastAPI(title="Damage Detection Backend")

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
        return result_json

    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Internal Server Error: {str(e)}")
    
    finally:
        if temp_input_path and os.path.exists(temp_input_path):
            # os.remove(temp_input_path)
            pass

if __name__ == "__main__":
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)