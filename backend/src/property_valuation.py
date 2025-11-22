import json
from typing import Dict
from datetime import datetime
import asyncio
import requests

THINKIMMO_API_URL = "https://thinkimmo-api.mgraetz.de/thinkimmo"

def fetch_market_appreciation_rate(address: str, current_price: float, property_type: str = "APARTMENTBUY") -> float:
    """Fetch appreciation rate from ThinkImmo API or return default"""
    city = address.split(',')[0].strip()
    
    city_map = {
        'munich': ('München', 'Bayern'),
        'münchen': ('München', 'Bayern'),
        'berlin': ('Berlin', 'Berlin'),
        'hamburg': ('Hamburg', 'Hamburg'),
        'frankfurt': ('Frankfurt', 'Hessen'),
        'cologne': ('Köln', 'Nordrhein-Westfalen'),
        'köln': ('Köln', 'Nordrhein-Westfalen'),
        'stuttgart': ('Stuttgart', 'Baden-Württemberg'),
        'düsseldorf': ('Düsseldorf', 'Nordrhein-Westfalen'),
        'dusseldorf': ('Düsseldorf', 'Nordrhein-Westfalen')
    }
    
    german_city, region = city_map.get(city.lower(), (city, 'Bayern'))
    
    request_data = {
        "active": True,
        "type": property_type,
        "sortBy": "desc",
        "sortKey": "grossReturn",
        "from": 0,
        "size": 50,
        "geoSearches": {
            "geoSearchQuery": german_city,
            "geoSearchType": "town",
            "region": region
        }
    }
    
    try:
        response = requests.post(
            THINKIMMO_API_URL,
            json=request_data,
            headers={"Content-Type": "application/json"},
            timeout=30
        )
        response.raise_for_status()
        
        results = response.json().get("results", [])
        if not results:
            return 0.015
        
        similar = [r for r in results if r.get("buyingPrice") and current_price * 0.7 <= r["buyingPrice"] <= current_price * 1.3]
        similar = similar or results[:10]
        
        gross_returns = [r["grossReturn"] for r in similar if r.get("grossReturn")]
        avg_gross_return = sum(gross_returns) / len(gross_returns) if gross_returns else 3.5
        
        if avg_gross_return > 5.0:
            return 0.025
        elif avg_gross_return > 4.0:
            return 0.02
        elif avg_gross_return > 3.0:
            return 0.015
        else:
            return 0.01
        
    except Exception:
        return 0.015

def calculate_10year_valuation(current_price: float, appreciation_rate: float) -> Dict:
    """Calculate 10-year property valuation with appreciation and rental income"""
    gross_return = appreciation_rate * 100 * 2
    annual_rental_income = current_price * gross_return / 100
    maintenance_factor = 0.01
    yearly_data = []
    cumulative_rental = 0
    
    for year in range(1, 11):
        property_value = current_price * ((1 + appreciation_rate) ** year)
        rental_income = annual_rental_income * ((1 + appreciation_rate * 0.5) ** year)
        cumulative_rental += rental_income
        maintenance_cost = property_value * maintenance_factor
        net_income = rental_income - maintenance_cost
        total_value = property_value + cumulative_rental - (maintenance_cost * year)
        roi = ((total_value - current_price) / current_price) * 100
        
        yearly_data.append({
            "year": year,
            "property_value": round(property_value, 2),
            "annual_rental_income": round(rental_income, 2),
            "cumulative_rental_income": round(cumulative_rental, 2),
            "maintenance_cost": round(maintenance_cost, 2),
            "net_annual_income": round(net_income, 2),
            "total_value": round(total_value, 2),
            "roi_percentage": round(roi, 2)
        })
    
    final = yearly_data[-1]
    
    return {
        "initial_price": current_price,
        "gross_return_percentage": gross_return,
        "appreciation_rate_percentage": appreciation_rate * 100,
        "annual_rental_income_initial": round(annual_rental_income, 2),
        "yearly_projections": yearly_data,
        "10_year_summary": {
            "final_property_value": final["property_value"],
            "total_rental_income": final["cumulative_rental_income"],
            "total_maintenance_costs": round(final["maintenance_cost"] * 10, 2),
            "total_return": round(final["total_value"] - current_price, 2),
            "total_roi_percentage": final["roi_percentage"]
        }
    }


def calculate_property_valuation_endpoint(
    current_price: float,
    address: str,
    property_type: str = "APARTMENTBUY"
) -> Dict:
    """Main endpoint function for property valuation"""
    appreciation_rate = fetch_market_appreciation_rate(address, current_price, property_type)
    source = "thinkimmo_api" if appreciation_rate != 0.015 else "default"
    valuation = calculate_10year_valuation(current_price, appreciation_rate)
    
    return {
        "timestamp": datetime.now().isoformat(),
        "input": {
            "address": address,
            "current_price": current_price,
            "property_type": property_type
        },
        "market_data": {
            "source": source,
            "appreciation_rate": appreciation_rate
        },
        "valuation": valuation
    }


if __name__ == "__main__":
    result = calculate_property_valuation_endpoint(
        current_price=450000,
        address="Berlin",
        property_type="APARTMENTBUY"
    )
    
    summary = result['valuation']['10_year_summary']
    print(f"\n{'='*80}\nPROPERTY VALUATION TEST\n{'='*80}")
    print(f"Address: {result['input']['address']}")
    print(f"Price: {result['input']['current_price']:,.2f} EUR")
    print(f"Appreciation Rate: {result['market_data']['appreciation_rate']*100:.2f}%")
    print(f"\n10-Year Summary:")
    print(f"  Final Value: {summary['final_property_value']:,.2f} EUR")
    print(f"  Total Return: {summary['total_return']:,.2f} EUR")
    print(f"  ROI: {summary['total_roi_percentage']:.2f}%")
    
    with open("property_valuation_test.json", "w") as f:
        json.dump(result, f, indent=2)
    print(f"\n✅ Saved to property_valuation_test.json")
