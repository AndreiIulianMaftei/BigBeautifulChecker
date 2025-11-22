
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
from multiprocessing import Pool
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

def detect_image_category(path_to_image: str) -> str:
    """First pass: Detect which main category the image belongs to"""
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
    
    # Validate category
    if detected_category not in CATEGORIES:
        # Try to find closest match
        for cat in CATEGORIES:
            if cat.lower() in detected_category.lower() or detected_category.lower() in cat.lower():
                detected_category = cat
                break
        else:
            # Default to Building Envelope if no match
            detected_category = "Building Envelope"
            print(f"Warning: Category not recognized, defaulting to {detected_category}")
    
    return detected_category

def get_subcategories_from_csv(category: str) -> list:
    """Load subcategories (Item/Subitem) from CSV for the detected category"""
    try:
        df = pd.read_csv(CSV_PATH)
        # Filter by category and get unique subcategories
        subcategories = df[df['Category'] == category]['Item/Subitem'].unique().tolist()
        print(f"Found {len(subcategories)} subcategories for '{category}'")
        return subcategories
    except Exception as e:
        print(f"Error loading subcategories: {e}")
        return []

def detect_single_image(path_to_image: str, subcategories: list):
    """Second pass: Detect damages using subcategories from CSV"""
    genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
    model = genai.GenerativeModel(os.getenv("model"))
    
    # Build subcategory list for prompt
    if subcategories:
        subcategory_text = ', '.join(subcategories[:50])  # Limit to avoid token overflow
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
    print(f"LLM response: {response.text}")
    return response.text

def get_bbox(path_to_image: str, destination_path: str):
    image = cv2.imread(path_to_image)
    height, width = image.shape[:2]

    # Stage 1: Detect category
    print("\n=== Stage 1: Detecting image category ===")
    detected_category = detect_image_category(path_to_image)
    
    # Stage 2: Get subcategories from CSV for that category
    print("\n=== Stage 2: Loading subcategories from CSV ===")
    subcategories = get_subcategories_from_csv(detected_category)
    
    # Stage 3: Detect damages with subcategories
    print("\n=== Stage 3: Detecting damages with subcategories ===")
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

        cv2.rectangle(image, (x_min, y_min), (x_max, y_max), color=(0,0,255), thickness=2)
        cv2.putText(image, label, (x_min, y_min - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0,0,255), 2)

    cv2.imwrite(destination_path, image)

    annotation_json = {
        "imageID" : os.path.splitext(os.path.basename(path_to_image))[0],
        "detected_category": detected_category,
        "annotation" : response_json
    }
    return annotation_json


if __name__=="__main__":
    # test single run
    test_image_path = pathlib.Path(CODEBASE_DIR / "sample_images/brokenwall.png")
    destination_path = pathlib.Path(CODEBASE_DIR / "sample_images/bbox_brokenwall.png")
    get_bbox(test_image_path, destination_path)

