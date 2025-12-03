
import re
import os
import sys
import cv2
import json
import time
import pandas as pd
import google.generativeai as genai
from pathlib import Path
from dotenv import load_dotenv
import asyncio
import pathlib

CODEBASE_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(CODEBASE_DIR))

load_dotenv() 

CATEGORIES = [
    "Heating / Ventilation / Climate",
    "Central Hot Water Preparation",
    "Chimney",
    "Building Envelope",
    "Ceilings / Walls / Doors",
    "Floor Coverings",
    "Kitchen",
    "Bath / Shower / WC",
    "TV and Radio Reception / Electrical Systems",
    "Balconies / Sun Blinds / Conservatory",
    "Basement and Attic Expansion",
    "Elevator",
    "Community Facilities",
    "Reductions for Special Use"
]

CSV_PATH = Path(CODEBASE_DIR) / "dataset" / "message.csv"

def get_severity_color(severity) -> tuple:
    """Return BGR color based on severity level (1-5)"""
    try:
        severity_int = int(severity)
    except (ValueError, TypeError):
        severity_int = 3  
    
    if severity_int == 1:
        return (0, 255, 0)      
    elif severity_int in [2, 3]:
        return (0, 165, 255)   
    else:  # 4-5
        return (0, 0, 255)     

def detect_image_category(path_to_image: str) -> str:
    genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
    model = genai.GenerativeModel(os.getenv("model"))
    
    category_prompt = f"""Analyze this image of a building interior or exterior and determine which ONE category it belongs to.
    
    Choose ONLY ONE category from this list:
    {chr(10).join([f"- {cat}" for cat in CATEGORIES])}
    
    Return ONLY the exact category name, nothing else.
    """
    
    from PIL import Image
    image = Image.open(path_to_image)
    
    response = model.generate_content([category_prompt, image])
    
    detected_category = response.text.strip()
    print(f"Detected category: {detected_category}")
    
    if detected_category not in CATEGORIES:
        for cat in CATEGORIES:
            if cat.lower() in detected_category.lower() or detected_category.lower() in cat.lower():
                detected_category = cat
                break
        else:
            detected_category = "Building Envelope"
            print(f"Warning: Category not recognized, defaulting to {detected_category}")
    
    return detected_category

def get_subcategories_from_csv(category: str) -> list:
    try:
        df = pd.read_csv(CSV_PATH)
        subcategories = df[df['Category'] == category]['Item/Subitem'].unique().tolist()
        print(f"Found {len(subcategories)} subcategories for '{category}'")
        return subcategories
    except Exception as e:
        print(f"Error loading subcategories: {e}")
        return []

def detect_single_image(path_to_image: str, subcategories: list):
    genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
    model = genai.GenerativeModel(os.getenv("model"))
    
    if subcategories:
        subcategory_text = ', '.join(subcategories[:50])
        if len(subcategories) > 50:
            subcategory_text += ', and more...'
    else:
        subcategory_text = 'any building component'
    
    std_detection_prompt = f"""Please locate the damages in the given image of house interior and exterior and output the bounding boxes. Be as precise as possible. But only list the damages that you are very confident about, and only list the ones that are evident. The box_2d should be [ymin, xmin, ymax, xmax] normalized to 0-1000."
    Important: Only return the json object nothing else.

    Analyze the image and identify any damage types present. Use descriptive labels for the damage types you detect.
    
    SEVERITY GUIDELINES - Be realistic and err on the side of caution:
    - If damage is VISIBLE and APPARENT (clearly visible structural issues, active leaks, exposed wiring, large cracks, significant water damage, mold growth): Assign severity 4-5 immediately. These require urgent attention.
    - If damage is MODERATE but contained (small cracks, minor discoloration, slight wear, cosmetic issues): Assign severity 2-3. These can be addressed over time.
    - Only assign severity 1 for truly cosmetic issues that don't affect function or safety.
    - When in doubt about apparent damage, lean towards Medium severity (3-5) rather than lower. It's better to flag potential problems early.
    
    subcategory_type should be one of the following building components from the database: {subcategory_text}
    
    Choose the most appropriate subcategory that matches the damaged component.
    
    The output format should be a JSON array where each element has the following structure:
    {{
        "label": "<damage_type>",
        "box_2d": [ymin, xmin, ymax, xmax],
        "severity": "<severity_level>",
        "subcategory": "<subcategory_type>"
    }}
    """
    from PIL import Image
    image = Image.open(path_to_image)

    response = model.generate_content([std_detection_prompt, image])
    response_text = response.text
    print(f"LLM response: {response_text[:500]}...")  # Print first 500 chars
    
    # Check if LLM refused or returned empty
    if not response_text or response_text.strip() == "[]":
        print("WARNING: Gemini returned empty array - possible API quota exceeded or model refusal")
        print("TIP: Try uploading actual building damage images, not maps or general property photos")
    
    return response_text

async def process_single_image_async(path_to_image: str, destination_path: str):
    loop = asyncio.get_event_loop()
    
    detected_category = await loop.run_in_executor(None, detect_image_category, path_to_image)
    
    subcategories = get_subcategories_from_csv(detected_category)
    
    response_text = await loop.run_in_executor(None, detect_single_image, path_to_image, subcategories)
    
    image = cv2.imread(path_to_image)
    height, width = image.shape[:2]

    try:
        lines = response_text.strip().split('\n')
        json_content_lines = lines[1:-1]
        clean_json_string = "\n".join(json_content_lines)
        response_json = json.loads(clean_json_string)
    except json.JSONDecodeError as e:
        print(f"Error decoding JSON: {e}")
        return {}

    for item in response_json:
        y0, x0, y1, x1 = item["box_2d"]
        x_min = int(x0 / 1000 * width)
        y_min = int(y0 / 1000 * height)
        x_max = int(x1 / 1000 * width)
        y_max = int(y1 / 1000 * height)
        label = item["label"]
        severity = item.get("severity", 3)
        color = get_severity_color(severity)
        cv2.rectangle(image, (x_min, y_min), (x_max, y_max), color=color, thickness=2)
        cv2.putText(image, f"{label} (S:{severity})", (x_min, y_min - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.9, color, 2)

    cv2.imwrite(destination_path, image)

    annotation_json = {
        "imageID": os.path.splitext(os.path.basename(path_to_image))[0],
        "detected_category": detected_category,
        "annotation": response_json
    }
    return annotation_json

async def get_bbox_async(path_to_image: str, destination_path: str):
    return await process_single_image_async(path_to_image, destination_path)

def get_bbox(path_to_image: str, destination_path: str):
    image = cv2.imread(path_to_image)
    height, width = image.shape[:2]

    detected_category = detect_image_category(path_to_image)
    subcategories = get_subcategories_from_csv(detected_category)
    response_text = detect_single_image(path_to_image, subcategories)

    try:
        lines = response_text.strip().split('\n')
        json_content_lines = lines[1:-1]
        clean_json_string = "\n".join(json_content_lines)
        response_json = json.loads(clean_json_string)
    except json.JSONDecodeError as e:
        print(f"Error decoding JSON: {e}")
        return {}

    for item in response_json:
        y0, x0, y1, x1 = item["box_2d"]
        x_min = int(x0 / 1000 * width)
        y_min = int(y0 / 1000 * height)
        x_max = int(x1 / 1000 * width)
        y_max = int(y1 / 1000 * height)
        label = item["label"]
        severity = item.get("severity", 3)
        color = get_severity_color(severity)
        cv2.rectangle(image, (x_min, y_min), (x_max, y_max), color=color, thickness=2)
        cv2.putText(image, f"{label} (S:{severity})", (x_min, y_min - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.9, color, 2)

    cv2.imwrite(destination_path, image)

    annotation_json = {
        "imageID": os.path.splitext(os.path.basename(path_to_image))[0],
        "detected_category": detected_category,
        "annotation": response_json
    }
    return annotation_json


if __name__=="__main__":
    # test single run
    test_image_path = pathlib.Path(CODEBASE_DIR / "sample_images/brokenwall.png")
    destination_path = pathlib.Path(CODEBASE_DIR / "sample_images/bbox_brokenwall.png")
    get_bbox(test_image_path, destination_path)

