"""
Simple example script for ThinkImmo API
Makes one request and prints the response - standalone version
"""

import requests
import json

# API endpoint
API_URL = "https://thinkimmo-api.mgraetz.de/thinkimmo"

# Build request payload
request_data = {
    "active": True,
    "type": "APARTMENTBUY",
    "sortBy": "desc",
    "sortKey": "pricePerSqm",
    "from": 0,
    "size": 10,
    "geoSearches": {
        "geoSearchQuery": "München",
        "geoSearchType": "town",
        "region": "Bayern"
    }
}

print("Searching for apartments in Munich...\n")
# Print HTTP request details
print("="*70)
print("HTTP REQUEST")
print("="*70)
print(f"POST {API_URL}")
print("Content-Type: application/json")
print("\nRequest Body:")
print(json.dumps(request_data, indent=2))
print()

try:
    # Make the API request
    response = requests.post(
        API_URL,
        json=request_data,
        headers={"Content-Type": "application/json"},
        timeout=30,
    )
    
    print("="*70)
    print("HTTP RESPONSE")
    print("="*70)
    print(f"Status Code: {response.status_code}")
    print(f"Content-Type: {response.headers.get('Content-Type', 'N/A')}")
    print()
    
    # Check if request was successful
    response.raise_for_status()
    
    # Parse JSON response
    data = response.json()
    
    # Print the full response
    print("="*70)
    print("API RESPONSE DATA")
    print("="*70)
    print(json.dumps(data, indent=2, ensure_ascii=False))
    
    # Print a summary
    print("\n" + "="*70)
    print("SUMMARY")
    print("="*70)
    print(f"Total listings: {data.get('total', 0)}")
    print(f"Results returned: {len(data.get('results', []))}")
    
    if data.get('results'):
        print("\nFirst listing:")
        first = data['results'][0]
        print(f"  Title: {first.get('title')}")
        print(f"  Price: €{first.get('buyingPrice', 0):,}")
        print(f"  Size: {first.get('squareMeter', 0)} m²")
        print(f"  Location: {first.get('address', {}).get('displayName', 'N/A')}")
    
except requests.exceptions.HTTPError as e:
    print(f"HTTP Error: {e}")
    if 'response' in locals():
        print(f"Response: {response.text[:500]}")
except requests.exceptions.RequestException as e:
    print(f"Request Error: {e}")
except Exception as e:
    print(f"Error: {e}")