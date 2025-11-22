"""
Test script for price calculator integration with FastAPI
"""
import asyncio
import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from price_calculator import analyze_damages_for_endpoint

async def test_price_calculator():
    """Test the price calculator with mock data"""
    print("Testing price calculator integration...")
    print("=" * 80)
    
    # Test data that mimics detection output
    damage_items = [
        {"item": "Boiler", "severity": 5},
        {"item": "crack", "severity": 3}
    ]
    
    print(f"\nInput damage items: {damage_items}")
    print("\nRunning analysis with mock data...\n")
    
    result = await analyze_damages_for_endpoint(
        damage_items=damage_items,
        use_mock=True,  # Use mock to avoid API quota
        max_concurrent=2
    )
    
    print("\n" + "=" * 80)
    print("RESULTS:")
    print("=" * 80)
    print(f"Status: {result['status']}")
    print(f"Total items analyzed: {result['summary']['total_items_analyzed']}")
    print(f"10-year total cost: {result['summary']['grand_total_10year_cost_chf']} CHF")
    
    if result['analyses']:
        print("\nDetailed breakdown:")
        for analysis in result['analyses']:
            item = analysis['damage_item']
            cost = analysis['ten_year_projection']['total_10year_cost']
            print(f"  - {item}: {cost} CHF")
    
    print("\n✅ Integration test passed!")
    return result

if __name__ == "__main__":
    asyncio.run(test_price_calculator())
