
import re
import os
import sys
import cv2
import json
import time
from google import genai
from pathlib import Path
from google.genai import types
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

def detect_single_image(path_to_image : str, classes: list):
    client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
    std_detection_prompt = f"""Please locate the damages in the given image of house interior and exterior and output the bounding boxes. Be as precise as possible. But only list the damages that you are very confident about, and only list the ones that are evident. The box_2d should be [ymin, xmin, ymax, xmax] normalized to 0-1000."
    Important: Only return the json object nothing else.

    The possible damage types are: {', '.join(classes) if classes else 'crack, mold, water_damage, rust, broken_window, chipped_paint, sagging_roof, damaged_door, faulty_wiring, leaking_pipe'}.
    severity_level should range from 1 to 5. 1 indicates minor damage while 5 indicates severe damage.
    category_type should be one of the follwoing values. The values should be exactly how it's in this list: {', '.join(CATEGORIES)}
    The output format should be a JSON array where each element has the following structure:
    {{
        "label": "<damage_type>",
        "box_2d": [ymin, xmin, ymax, xmax],
        "severity": "<severity_level>",
        "catagory": <category_type>
    }}
    """
    with open(path_to_image, 'rb') as f:
        image_bytes = f.read()

    response = client.models.generate_content(
        model=os.getenv("model"),
        contents=[
            types.Part.from_bytes(
                data=image_bytes,
                mime_type='image/jpeg',
            ),
            std_detection_prompt
        ]
    )
    print(f"LLM response: {response.text}")
    return response.text

def get_bbox(path_to_image: str, destination_path: str, classes: list):
    image = cv2.imread(path_to_image)
    height, width = image.shape[:2]

    response_text = detect_single_image(path_to_image, classes)

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
        "annotation" : response_json
    }
    return annotation_json


if __name__=="__main__":
    # test single run
    test_image_path = pathlib.Path(CODEBASE_DIR / "sample_images/brokenwall.png")
    destination_path = pathlib.Path(CODEBASE_DIR / "sample_images/bbox_brokenwall.png")
    get_bbox(test_image_path, destination_path, [])

