import pandas as pd
import google.generativeai as genai
import os
import json
import dotenv
import asyncio
from typing import Dict, List, Tuple

dotenv.load_dotenv()

def load_damage_database(csv_path: str) -> pd.DataFrame:
    df = pd.read_csv(csv_path)
    return df

def find_damage_in_csv(df: pd.DataFrame, damage_item: str) -> pd.DataFrame:
    # Use regex=False to treat special characters literally (e.g., parentheses, brackets)
    matches = df[df['Item/Subitem'].str.contains(damage_item, case=False, na=False, regex=False)]
    return matches

def complete_missing_data_prompt(damage_item: str, partial_data: Dict) -> str:
    """Generate prompt to complete missing data using LLM"""
    return f"""
You are an expert in building maintenance and repair cost estimation.

Given this partial data about "{damage_item}":
Category: {partial_data.get('Category', 'Unknown')}
Item: {partial_data.get('Item/Subitem', 'Unknown')}
Lifespan: {partial_data.get('Lifespan (Years)', 'Missing')} years
Price Type: {partial_data.get('Price Type', 'Missing')}
Price: {partial_data.get('Price (CHF)', 'Missing')} CHF
Unit: {partial_data.get('Unit', 'Missing')}

Please provide CONSERVATIVE estimates for any missing data (marked as '-' or 'Missing').
Consider industry standards for Swiss building maintenance.
ERR ON THE SIDE OF HIGHER COSTS to account for unforeseen complications and price variations.
Add 15-20% buffer to typical costs for realistic project planning.

Return ONLY a valid JSON object with this structure:
{{
    "lifespan_years": <number or original if present>,
    "price_type": "<Replacement/Repair/New Coat/etc>",
    "price_chf": <number>,
    "unit": "<per piece/per m²/per m/etc>",
    "reasoning": "<brief explanation of estimates>"
}}
"""

def predict_repair_schedule_prompt(damage_item: str, complete_data: Dict, severity: int) -> str:
    """Generate prompt to predict repair schedule based on severity"""
    return f"""
You are an expert maintenance scheduler for building components.

Item: {damage_item}
Category: {complete_data.get('Category', 'Unknown')}
Normal Lifespan: {complete_data.get('lifespan_years')} years
Base Cost: {complete_data.get('price_chf')} CHF {complete_data.get('unit')}
Damage Severity: {severity}/5 (where 1 is minimal damage and 5 is critical/urgent)

Based on the severity level, predict:
1. When the next repair/replacement will be needed (be CONSERVATIVE - higher severity means sooner action)
2. Whether additional maintenance will be needed before replacement
3. How severity affects the timeline and costs

IMPORTANT:
- For severity 4-5: Consider URGENT action (within 1-2 years) and add 20-30% cost buffer
- For severity 3: Plan within 2-4 years with 15% cost buffer
- For severity 1-2: Follow normal schedule but include preventive maintenance
- Always include contingency costs (10-30% depending on severity)
- Account for potential hidden damages that often accompany visible issues

Return ONLY a valid JSON object:
{{
    "next_repair_year": <year from now, 0-10>,
    "repair_type": "<Maintenance/Repair/Replacement>",
    "estimated_cost": <cost in CHF>,
    "additional_maintenance": [
        {{"year": <0-10>, "type": "<description>", "cost": <CHF>}}
    ],
    "severity_impact": "<explanation>"
}}
"""

def calculate_10year_projection(damage_item: str, repair_schedule: Dict, complete_data: Dict) -> Dict:
    """Calculate 10-year cost projection numerically based on repair schedule"""
    INFLATION_RATE = 0.035  # 3.5% per year (conservative estimate for Swiss building costs)
    CONTINGENCY_BUFFER = 0.15  # 15% contingency buffer for unforeseen costs
    yearly_costs = []
    cumulative_cost = 0
    
    # Create a schedule map for easy lookup
    scheduled_events = {}
    
    # Add main repair/replacement
    next_repair_year = repair_schedule.get('next_repair_year', 0)
    if 0 < next_repair_year <= 10:
        scheduled_events[next_repair_year] = {
            'type': repair_schedule.get('repair_type', 'Repair'),
            'cost': repair_schedule.get('estimated_cost', 0)
        }
    
    # Add additional maintenance events
    for maint in repair_schedule.get('additional_maintenance', []):
        maint_year = maint.get('year', 0)
        if 0 < maint_year <= 10:
            if maint_year in scheduled_events:
                # Add to existing year
                scheduled_events[maint_year]['cost'] += maint.get('cost', 0)
                scheduled_events[maint_year]['type'] += f" + {maint.get('type', 'Maintenance')}"
            else:
                scheduled_events[maint_year] = {
                    'type': maint.get('type', 'Maintenance'),
                    'cost': maint.get('cost', 0)
                }
    
    # Generate yearly breakdown
    for year in range(1, 11):
        if year in scheduled_events:
            event = scheduled_events[year]
            # Apply inflation and contingency buffer to the cost
            base_cost = event['cost'] * (1 + CONTINGENCY_BUFFER)
            inflated_cost = base_cost * ((1 + INFLATION_RATE) ** (year - 1))
            scheduled_work = event['type']
            notes = f"Scheduled {event['type'].lower()} with {INFLATION_RATE*100}% inflation + {CONTINGENCY_BUFFER*100}% contingency"
        else:
            inflated_cost = 0
            scheduled_work = "none"
            notes = "No scheduled work"
        
        cumulative_cost += inflated_cost
        
        yearly_costs.append({
            'year': year,
            'scheduled_work': scheduled_work,
            'cost': round(inflated_cost, 2),
            'cumulative_cost': round(cumulative_cost, 2),
            'notes': notes
        })
    
    # Generate summary
    num_events = len([y for y in yearly_costs if y['cost'] > 0])
    summary = f"Total of {num_events} maintenance/repair event(s) scheduled over 10 years. "
    summary += f"Costs include {INFLATION_RATE*100}% annual inflation and {CONTINGENCY_BUFFER*100}% contingency buffer for conservative planning."
    
    return {
        'yearly_costs': yearly_costs,
        'total_10year_cost': round(cumulative_cost, 2),
        'summary': summary
    }

async def call_ai_model(prompt: str, use_mock: bool = False) -> str:
    """Call Gemini AI model with quota handling"""
    if use_mock:
        # Mock responses for testing without API quota
        if "complete missing data" in prompt.lower():
            await asyncio.sleep(0.1)  # Simulate API delay
            return json.dumps({
                "lifespan_years": 20,
                "price_type": "Replacement",
                "price_chf": 500,
                "unit": "per piece",
                "reasoning": "Mock data for testing"
            })
        elif "predict repair schedule" in prompt.lower():
            await asyncio.sleep(0.1)  # Simulate API delay
            return json.dumps({
                "next_repair_year": 3,
                "repair_type": "Maintenance",
                "estimated_cost": 300,
                "additional_maintenance": [
                    {"year": 5, "type": "Inspection", "cost": 100}
                ],
                "severity_impact": "Mock severity impact"
            })

    # Run API call in thread pool to avoid blocking
    loop = asyncio.get_event_loop()
    genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
    response = await loop.run_in_executor(
        None,
        lambda: genai.GenerativeModel('gemini-2.0-flash-exp').generate_content(prompt)
    )
    return response.text

async def analyze_damage(damage_item: str, severity: int, csv_path: str, use_mock: bool = False) -> Dict:
    """Main function to analyze damage and generate cost projections"""
    
    print(f"\n{'='*60}")
    print(f"Analyzing: {damage_item}")
    print(f"Severity: {severity}/5")
    print(f"{'='*60}\n")
    
    # Step 1: Load CSV and find damage
    print("Step 1: Loading database and finding damage item...")
    df = load_damage_database(csv_path)
    matches = find_damage_in_csv(df, damage_item)
    
    if matches.empty:
        print(f"❌ No matches found for '{damage_item}' in database")
        return None
    
    print(f"✅ Found {len(matches)} match(es)")
    item_data = matches.iloc[0].to_dict()
    print(f"   Category: {item_data['Category']}")
    print(f"   Item: {item_data['Item/Subitem']}")
    
    # Step 2: Complete missing data with LLM
    print("\nStep 2: Completing missing data with LLM...")
    has_missing = (item_data['Price (CHF)'] == '-' or 
                   pd.isna(item_data['Price (CHF)']) or
                   item_data['Price Type'] == '-')
    
    if has_missing:
        prompt = complete_missing_data_prompt(damage_item, item_data)
        response = await call_ai_model(prompt, use_mock)
        complete_data = json.loads(response.strip().replace('```json', '').replace('```', ''))
        complete_data['Category'] = item_data['Category']
        complete_data['Item'] = item_data['Item/Subitem']
        print(f"✅ Completed data: {complete_data['price_chf']} CHF {complete_data['unit']}")
    else:
        complete_data = {
            'Category': item_data['Category'],
            'Item': item_data['Item/Subitem'],
            'lifespan_years': item_data['Lifespan (Years)'],
            'price_type': item_data['Price Type'],
            'price_chf': item_data['Price (CHF)'],
            'unit': item_data['Unit']
        }
        print(f"✅ Data already complete: {complete_data['price_chf']} CHF {complete_data['unit']}")
    
    # Step 3: Predict repair schedule
    print("\nStep 3: Predicting repair schedule based on severity...")
    prompt = predict_repair_schedule_prompt(damage_item, complete_data, severity)
    response = await call_ai_model(prompt, use_mock)
    repair_schedule = json.loads(response.strip().replace('```json', '').replace('```', ''))
    print(f"✅ Next repair in year: {repair_schedule['next_repair_year']}")
    print(f"   Type: {repair_schedule['repair_type']}")
    print(f"   Estimated cost: {repair_schedule['estimated_cost']} CHF")
    
    # Step 4: Calculate 10-year cost table numerically
    print("\nStep 4: Calculating 10-year cost projection table...")
    ten_year_table = calculate_10year_projection(damage_item, repair_schedule, complete_data)
    print(f"✅ 10-year total cost: {ten_year_table['total_10year_cost']} CHF")
    
    return {
        'damage_item': damage_item,
        'severity': severity,
        'complete_data': complete_data,
        'repair_schedule': repair_schedule,
        'ten_year_projection': ten_year_table
    }

def print_cost_table(analysis_result: Dict):
    """Print a formatted 10-year cost table"""
    if not analysis_result:
        return
    
    print(f"\n{'='*80}")
    print(f"10-YEAR COST PROJECTION: {analysis_result['damage_item']}")
    print(f"{'='*80}")
    
    table = analysis_result['ten_year_projection']['yearly_costs']
    print(f"\n{'Year':<6} {'Scheduled Work':<30} {'Cost (CHF)':<12} {'Cumulative (CHF)':<15} {'Notes'}")
    print(f"{'-'*80}")
    
    for row in table:
        print(f"{row['year']:<6} {row['scheduled_work']:<30} {row['cost']:<12.2f} {row['cumulative_cost']:<15.2f} {row['notes']}")
    
    print(f"{'-'*80}")
    print(f"Total 10-Year Cost: {analysis_result['ten_year_projection']['total_10year_cost']} CHF")
    print(f"\nSummary: {analysis_result['ten_year_projection']['summary']}")
    print(f"{'='*80}\n")

def save_analysis_to_file(analysis_result: Dict, file_path: str):
    """Save complete analysis to JSON file"""
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(analysis_result, f, indent=2, ensure_ascii=False)
    print(f"Analysis saved to: {file_path}")


async def analyze_damage_with_semaphore(semaphore: asyncio.Semaphore, test: Dict, csv_path: str, use_mock: bool, test_num: int, total: int) -> Dict:
    """Wrapper to run analyze_damage with semaphore for concurrency control"""
    async with semaphore:
        print(f"\n{'='*80}")
        print(f"TEST CASE {test_num}/{total} - Starting...")
        print(f"{'='*80}")
        
        result = await analyze_damage(
            damage_item=test["item"],
            severity=test["severity"],
            csv_path=csv_path,
            use_mock=use_mock
        )
        
        if result:
            print_cost_table(result)
            
            # Save individual analysis
            filename = f"analysis_{test['item'].replace(' ', '_').replace('/', '_')}.json"
            save_analysis_to_file(result, filename)
        
        return result

async def run_analyses_async(test_cases: List[Dict], csv_path: str, use_mock: bool, max_concurrent: int = 5) -> List[Dict]:
    """Run multiple damage analyses concurrently with a maximum limit"""
    semaphore = asyncio.Semaphore(max_concurrent)
    
    tasks = [
        analyze_damage_with_semaphore(semaphore, test, csv_path, use_mock, i+1, len(test_cases))
        for i, test in enumerate(test_cases)
    ]
    
    results = await asyncio.gather(*tasks)
    return [r for r in results if r is not None]

async def analyze_damages_for_endpoint(damage_items: List[Dict], csv_path: str = None, use_mock: bool = False, max_concurrent: int = 5) -> Dict:
    """
    Main function for API endpoint - analyzes multiple damage items and returns structured response
    
    Args:
        damage_items: List of damage items with format:
            [{
                "item": "Boiler",
                "severity": 4  # 1-5 scale (1=minimal, 5=critical)
            }]
        csv_path: Path to CSV database
        use_mock: Whether to use mock data (for testing)
        max_concurrent: Maximum concurrent API calls
    
    Returns:
        Dictionary with complete analysis results in API-ready format
    """
    # Default CSV path relative to backend directory
    if csv_path is None:
        csv_path = os.path.join(os.path.dirname(__file__), "..", "..", "dataset", "message.csv")
    semaphore = asyncio.Semaphore(max_concurrent)
    
    tasks = [
        analyze_damage(
            damage_item=item["item"],
            severity=item["severity"],
            csv_path=csv_path,
            use_mock=use_mock
        )
        for item in damage_items
    ]
    
    # Run all analyses concurrently
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # Filter out None and exceptions
    successful_results = []
    failed_items = []
    
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            failed_items.append({
                "item": damage_items[i]["item"],
                "error": str(result)
            })
        elif result is not None:
            successful_results.append(result)
        else:
            failed_items.append({
                "item": damage_items[i]["item"],
                "error": "Item not found in database"
            })
    
    # Calculate totals
    grand_total = sum(r['ten_year_projection']['total_10year_cost'] for r in successful_results)
    
    # Build response
    response = {
        "status": "success",
        "timestamp": pd.Timestamp.now().isoformat(),
        "summary": {
            "total_items_analyzed": len(successful_results),
            "total_items_requested": len(damage_items),
            "failed_items_count": len(failed_items),
            "grand_total_10year_cost_chf": round(grand_total, 2)
        },
        "analyses": successful_results,
        "failed_items": failed_items if failed_items else None
    }
    
    return response

if __name__ == "__main__":
    # Configuration
    CSV_PATH = "../dataset/message.csv"
    USE_MOCK = True  # Set to False to use real API (requires quota)
    MAX_CONCURRENT = 5  # Maximum concurrent API calls
    
    print("\nBUILDING DAMAGE ANALYSIS SYSTEM")
    print("="*80)
    print(f"Max concurrent analyses: {MAX_CONCURRENT}")
    print("="*80)
    
    # Test cases with different items and severities
    test_cases = [
        {
            "item": "Boiler",
            "severity": 5
        },
        {
            "item": "Thermostatic Radiator Valves",
            "severity": 3
        },
        {
            "item": "Air Conditioning Units",
            "severity": 1
        }
    ]
    
    # Run analyses using endpoint function
    response = asyncio.run(analyze_damages_for_endpoint(
        damage_items=test_cases,
        csv_path=CSV_PATH,
        use_mock=USE_MOCK,
        max_concurrent=MAX_CONCURRENT
    ))
    
    # Print summary
    print(f"\n{'='*80}")
    print(f"ANALYSIS COMPLETE")
    print(f"{'='*80}")
    print(f"Status: {response['status']}")
    print(f"Items analyzed: {response['summary']['total_items_analyzed']}/{response['summary']['total_items_requested']}")
    print(f"Grand Total (10 years): {response['summary']['grand_total_10year_cost_chf']} CHF")
    
    if response['failed_items']:
        print(f"\nWARNING: Failed items: {response['summary']['failed_items_count']}")
        for failed in response['failed_items']:
            print(f"   - {failed['item']}: {failed['error']}")
    
    print(f"\n{'='*80}")
    print("Individual Results:")
    print(f"{'='*80}")
    for analysis in response['analyses']:
        total = analysis['ten_year_projection']['total_10year_cost']
        print(f"   - {analysis['damage_item']}: {total} CHF")
    
    # Save complete response
    save_analysis_to_file(response, "api_response.json")
    
    print(f"\n{'='*80}")
    print("Analysis complete! Response saved to api_response.json")
    print(f"{'='*80}\n")
    
    # Print example JSON format for API documentation
    print("\nAPI Response Format Example:")
    print("="*80)
    example_format = {
        "status": "success",
        "timestamp": "2025-11-22T10:30:00.123456",
        "summary": {
            "total_items_analyzed": 3,
            "total_items_requested": 3,
            "failed_items_count": 0,
            "grand_total_10year_cost_chf": 1200.50
        },
        "analyses": [
            {
                "damage_item": "Boiler",
                "severity": 5,
                "complete_data": {
                    "Category": "Heating / Ventilation / Climate",
                    "Item": "Boiler",
                    "lifespan_years": 20,
                    "price_type": "Replacement",
                    "price_chf": 5000,
                    "unit": "per piece"
                },
                "repair_schedule": {
                    "next_repair_year": 2,
                    "repair_type": "Replacement",
                    "estimated_cost": 5000,
                    "additional_maintenance": [
                        {"year": 1, "type": "Inspection", "cost": 200}
                    ],
                    "severity_impact": "Critical severity requires immediate attention"
                },
                "ten_year_projection": {
                    "yearly_costs": [
                        {
                            "year": 1,
                            "scheduled_work": "Inspection",
                            "cost": 200.0,
                            "cumulative_cost": 200.0,
                            "notes": "Scheduled inspection with 2.0% inflation"
                        },
                        # ... years 2-10
                    ],
                    "total_10year_cost": 5200.50,
                    "summary": "Total of 2 maintenance/repair event(s) scheduled over 10 years."
                }
            }
            # ... more analyses
        ],
        "failed_items": None
    }
    print(json.dumps(example_format, indent=2))
    print("="*80)
