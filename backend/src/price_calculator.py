import pandas as pd
import google.generativeai as genai
import os
import json
import dotenv
import asyncio
from typing import Dict, List, Tuple, Optional

dotenv.load_dotenv()

def load_damage_database(csv_path: str) -> pd.DataFrame:
    """Load the CSV database of building components and their costs."""
    df = pd.read_csv(csv_path)
    return df

def find_damage_in_csv(df: pd.DataFrame, damage_item: str) -> pd.DataFrame:
    """Search for damage item in CSV database."""
    # Use regex=False to treat special characters literally (e.g., parentheses, brackets)
    matches = df[df['Item/Subitem'].str.contains(damage_item, case=False, na=False, regex=False)]
    return matches

def parse_csv_data(item_data: Dict) -> Optional[Dict]:
    """
    Parse CSV data directly without LLM when possible.
    Returns a structured dict with the data, or None if LLM is needed.
    """
    # Check if we have all the critical data
    price = item_data.get('Price (EUR)')
    unit = item_data.get('Unit')
    lifespan = item_data.get('Lifespan (Years)')
    price_type = item_data.get('Price Type')
    
    # If any critical field is missing or '-', we need LLM
    if (price == '-' or pd.isna(price) or 
        unit == '-' or pd.isna(unit) or
        lifespan == '-' or pd.isna(lifespan) or
        price_type == '-' or pd.isna(price_type)):
        return None
    
    # We have complete data, parse it directly
    try:
        return {
            'Category': str(item_data.get('Category', 'Building Component')),
            'Item': str(item_data.get('Item/Subitem', 'Unknown')),
            'lifespan_years': int(lifespan),
            'price_type': str(price_type),
            'price_EUR': float(price),
            'unit': str(unit),
            'source': 'csv_direct'
        }
    except (ValueError, TypeError):
        # If parsing fails, fall back to LLM
        return None


def complete_missing_data_prompt(damage_item: str, partial_data: Dict) -> str:
    """
    Generate prompt to complete missing data using LLM.
    Designed to get accurate, realistic cost estimates.
    """
    is_completely_unknown = partial_data.get('Category') == 'Unknown'
    
    if is_completely_unknown:
        # Special prompt for completely unknown damage types
        return f"""You are an expert in building maintenance and repair cost estimation for Swiss/EU markets.

The damage type "{damage_item}" was NOT found in the standard building components database.

Analyze this damage and provide REALISTIC repair cost estimates:

IMPORTANT GUIDELINES:
1. Distinguish between immediate repair needs vs. long-term maintenance
2. For structural damage (walls, floors, ceilings): Minimum 150-300 EUR/m²
3. Include ALL costs: materials, Swiss labor rates (80-120 EUR/hour), disposal, permits
4. Add realistic markup: 20-30% for project overhead and contingencies
5. Consider hidden damage that may be discovered during repair

DAMAGE-SPECIFIC ESTIMATES:
- Wall damage/cracks: 250-500 EUR/m² for severe damage, 50-150 EUR/m² for minor
- Water damage: Include source repair + affected area restoration + mold prevention
- Mold remediation: 50-150 EUR/m² + source elimination
- Electrical issues: 80-120 EUR/hour + materials + permits (min 300 EUR)
- Broken windows: 300-1500 EUR per window
- Paint damage: 30-60 EUR/m² for repainting
- Plumbing leaks: 200-800 EUR for simple fixes, 1000+ EUR for major work

Return ONLY valid JSON:
{{
    "lifespan_years": <estimated years before next major work>,
    "price_type": "<Repair/Replacement/Remediation>",
    "price_EUR": <realistic base cost per unit>,
    "unit": "<per piece/per m²/per m/per hour>",
    "category": "<Building Envelope/Heating/Plumbing/Electrical/etc>",
    "reasoning": "<brief explanation of cost basis>"
}}"""
    else:
        # Original prompt for items found in database but with missing data
        return f"""You are an expert in building maintenance and repair cost estimation for Swiss/EU markets.

Item: "{damage_item}"
Known data:
- Category: {partial_data.get('Category', 'Unknown')}
- Lifespan: {partial_data.get('Lifespan (Years)', 'Missing')} years
- Price Type: {partial_data.get('Price Type', 'Missing')}
- Price: {partial_data.get('Price (EUR)', 'Missing')} EUR
- Unit: {partial_data.get('Unit', 'Missing')}

Complete the missing fields (marked as '-' or 'Missing') with REALISTIC estimates for Swiss/EU markets.

GUIDELINES:
- Swiss labor: 80-120 EUR/hour
- Materials markup: 20-30% over wholesale
- Include installation/disposal costs
- Be realistic, not optimistic

Return ONLY valid JSON:
{{
    "lifespan_years": <number or use existing>,
    "price_type": "<Replacement/Repair/New Coat>",
    "price_EUR": <cost per unit>,
    "unit": "<per piece/per m²/per m>",
    "reasoning": "<brief explanation>"
}}"""



def calculate_upfront_and_maintenance_prompt(damage_item: str, complete_data: Dict, severity: int) -> str:
    """
    Generate prompt to calculate UPFRONT repair cost and MAINTENANCE schedule.
    This replaces the old repair schedule prompt with clearer separation.
    """
    return f"""You are an expert maintenance scheduler for building components in Swiss/EU markets.

COMPONENT INFORMATION:
- Item: {damage_item}
- Category: {complete_data.get('Category', 'Unknown')}
- Normal Lifespan: {complete_data.get('lifespan_years')} years
- Base Cost: {complete_data.get('price_EUR')} EUR {complete_data.get('unit')}
- Damage Severity: {severity}/5 (1=minimal, 5=critical/destroyed)

YOUR TASK: Calculate TWO separate cost components:

1. UPFRONT REPAIR COST (if severity >= 2):
   - This is the IMMEDIATE cost to fix the existing damage
   - Apply severity multipliers:
     * Severity 2 (Minor): 1.2-1.5x base cost
     * Severity 3 (Moderate): 1.5-2.0x base cost
     * Severity 4 (Severe): 2.0-2.8x base cost
     * Severity 5 (Critical): 2.5-3.5x base cost
   - Include emergency repair premium if severity >= 4
   - Add 20-35% contingency for hidden damage
   - If severity = 1, upfront cost should be 0 or minimal inspection cost

2. MAINTENANCE SCHEDULE (10-year outlook):
   - Regular maintenance events to PREVENT future problems
   - Based on normal lifespan, NOT on current damage
   - Be MODERATE and REALISTIC:
     * Most items: 1-2 maintenance events over 10 years
     * Critical systems: Maybe 2-3 events
     * Simple components: 0-1 events
   - Typical maintenance costs: 10-20% of replacement cost
   - Inspection costs: 150-300 EUR (only if truly necessary)

IMPORTANT:
- Upfront cost is a ONE-TIME expense (year 0 or year 1)
- Maintenance is ongoing scheduled work
- Don't double-count - if upfront replaces the component, adjust maintenance accordingly
- Don't over-schedule maintenance

Return ONLY valid JSON:
{{
    "upfront_repair": {{
        "cost_EUR": <total upfront cost, 0 if severity=1>,
        "description": "<what will be repaired/replaced>",
        "severity_multiplier": <actual multiplier used>,
        "includes_contingency": true
    }},
    "maintenance_schedule": [
        {{
            "year": <1-10>,
            "type": "<Inspection/Maintenance/Minor Repair>",
            "cost_EUR": <cost>,
            "description": "<what maintenance work>"
        }}
        // 0-3 events total - be moderate!
    ],
    "reasoning": "<explain the upfront cost calculation and maintenance plan>"
}}"""



def calculate_10year_projection(damage_item: str, cost_data: Dict, complete_data: Dict) -> Dict:
    """
    Calculate 10-year cost projection with separate upfront and maintenance costs.
    Uses numerical calculation with inflation and contingency.
    """
    INFLATION_RATE = 0.045  # 4.5% per year (realistic for Swiss building/construction costs)
    CONTINGENCY_BUFFER = 0.15  # 15% contingency buffer (applied to maintenance, upfront already includes it)
    
    yearly_costs = []
    cumulative_cost = 0
    
    # Extract upfront and maintenance data
    upfront = cost_data.get('upfront_repair', {})
    upfront_cost = upfront.get('cost_EUR', 0)
    maintenance_schedule = cost_data.get('maintenance_schedule', [])
    
    # Create schedule map for maintenance
    maintenance_map = {}
    for maint in maintenance_schedule:
        year = maint.get('year', 0)
        if 1 <= year <= 10:
            if year not in maintenance_map:
                maintenance_map[year] = []
            maintenance_map[year].append(maint)
    
    # Year 0 breakdown (upfront cost)
    upfront_inflated = upfront_cost  # No inflation for immediate cost
    cumulative_cost += upfront_inflated
    
    year_0_data = {
        'year': 0,
        'upfront_cost': round(upfront_inflated, 2),
        'maintenance_cost': 0,
        'total_cost': round(upfront_inflated, 2),
        'cumulative_cost': round(cumulative_cost, 2),
        'work_description': upfront.get('description', 'Initial repair') if upfront_cost > 0 else 'No immediate repair needed',
        'is_upfront': True
    }
    
    # Generate yearly breakdown (years 1-10)
    for year in range(1, 11):
        maintenance_cost = 0
        descriptions = []
        
        if year in maintenance_map:
            for maint in maintenance_map[year]:
                base_maint_cost = maint.get('cost_EUR', 0)
                # Apply inflation and contingency to maintenance
                inflated_maint = base_maint_cost * (1 + CONTINGENCY_BUFFER) * ((1 + INFLATION_RATE) ** (year - 1))
                maintenance_cost += inflated_maint
                descriptions.append(maint.get('description', maint.get('type', 'Maintenance')))
        
        cumulative_cost += maintenance_cost
        
        yearly_costs.append({
            'year': year,
            'upfront_cost': 0,  # Upfront is only year 0
            'maintenance_cost': round(maintenance_cost, 2),
            'total_cost': round(maintenance_cost, 2),
            'cumulative_cost': round(cumulative_cost, 2),
            'work_description': ' + '.join(descriptions) if descriptions else 'No scheduled work',
            'is_upfront': False
        })
    
    # Calculate summary statistics
    total_maintenance = sum(y['maintenance_cost'] for y in yearly_costs)
    num_maintenance_events = len([y for y in yearly_costs if y['maintenance_cost'] > 0])
    
    summary = f"Upfront repair: {formatCurrency(upfront_cost)}. "
    summary += f"{num_maintenance_events} maintenance event(s) over 10 years totaling {formatCurrency(total_maintenance)}. "
    summary += f"Costs include {INFLATION_RATE*100}% annual inflation."
    
    # Key milestones (years 0, 1, 5, 10)
    key_years = {}
    key_years[0] = {
        'cumulative_cost': year_0_data['cumulative_cost'],
        'work_description': year_0_data['work_description']
    }
    for yc in yearly_costs:
        if yc['year'] in [1, 5, 10]:
            key_years[yc['year']] = {
                'cumulative_cost': yc['cumulative_cost'],
                'work_description': yc['work_description']
            }
    
    return {
        'upfront_cost': round(upfront_cost, 2),
        'total_maintenance_cost': round(total_maintenance, 2),
        'total_10year_cost': round(cumulative_cost, 2),
        'year_0': year_0_data,
        'yearly_costs': yearly_costs,
        'key_milestones': key_years,
        'summary': summary,
        'breakdown': {
            'immediate_repair_pct': round((upfront_cost / cumulative_cost * 100) if cumulative_cost > 0 else 0, 1),
            'ongoing_maintenance_pct': round((total_maintenance / cumulative_cost * 100) if cumulative_cost > 0 else 0, 1)
        }
    }

def formatCurrency(value):
    """Helper function to format currency values."""
    return f"{value:,.2f} EUR"


async def call_ai_model(prompt: str, use_mock: bool = False) -> str:
    """Call Gemini AI model with quota handling"""
    if use_mock:
        # Mock responses for testing without API quota
        if "complete missing data" in prompt.lower() or "complete the missing" in prompt.lower():
            await asyncio.sleep(0.1)  # Simulate API delay
            return json.dumps({
                "lifespan_years": 20,
                "price_type": "Replacement",
                "price_EUR": 500,
                "unit": "per piece",
                "reasoning": "Mock data for testing"
            })
        elif "calculate upfront" in prompt.lower() or "upfront repair cost" in prompt.lower():
            await asyncio.sleep(0.1)  # Simulate API delay
            return json.dumps({
                "upfront_repair": {
                    "cost_EUR": 1200,
                    "description": "Replace damaged component with modern equivalent",
                    "severity_multiplier": 2.0,
                    "includes_contingency": True
                },
                "maintenance_schedule": [
                    {"year": 5, "type": "Inspection", "cost_EUR": 200, "description": "Mid-term inspection"},
                    {"year": 9, "type": "Minor maintenance", "cost_EUR": 350, "description": "Preventive maintenance"}
                ],
                "reasoning": "Mock calculation for testing"
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
    """
    Main function to analyze damage and generate cost projections.
    Now with clear separation between upfront repair and maintenance costs.
    """
    
    print(f"\n{'='*60}")
    print(f"Analyzing: {damage_item}")
    print(f"Severity: {severity}/5")
    print(f"{'='*60}\n")
    
    # Step 1: Load CSV and find damage
    print("Step 1: Loading database and finding damage item...")
    df = load_damage_database(csv_path)
    matches = find_damage_in_csv(df, damage_item)
    
    if matches.empty:
        print(f"⚠️  No matches found for '{damage_item}' in database")
        print(f"📝 Using LLM to estimate all data for this damage type...")
        # Create empty item_data structure for LLM to complete
        item_data = {
            'Category': 'Unknown',
            'Item/Subitem': damage_item,
            'Lifespan (Years)': '-',
            'Price Type': '-',
            'Price (EUR)': '-',
            'Unit': '-'
        }
        complete_data = None
    else:
        print(f"✅ Found {len(matches)} match(es)")
        item_data = matches.iloc[0].to_dict()
        print(f"   Category: {item_data['Category']}")
        print(f"   Item: {item_data['Item/Subitem']}")
        
        # Try to parse CSV data directly (without LLM)
        complete_data = parse_csv_data(item_data)
        if complete_data:
            print(f"✅ Complete data from CSV: {complete_data['price_EUR']} EUR {complete_data['unit']}")
    
    # Step 2: Complete missing data with LLM if needed
    if not complete_data:
        print("\nStep 2: Completing missing data with LLM...")
        prompt = complete_missing_data_prompt(damage_item, item_data)
        response = await call_ai_model(prompt, use_mock)
        
        try:
            complete_data = json.loads(response.strip().replace('```json', '').replace('```', ''))
            
            # Use category from LLM if it was unknown, otherwise use database category
            if item_data.get('Category') == 'Unknown':
                complete_data['Category'] = complete_data.get('category', 'Building Envelope')
                print(f"✅ LLM estimated category: {complete_data['Category']}")
            else:
                complete_data['Category'] = item_data['Category']
            
            complete_data['Item'] = item_data['Item/Subitem']
            complete_data['source'] = 'llm_completed'
            print(f"✅ Completed data: {complete_data['price_EUR']} EUR {complete_data['unit']}")
            if 'reasoning' in complete_data:
                print(f"   Reasoning: {complete_data['reasoning']}")
        except json.JSONDecodeError as e:
            print(f"❌ Error parsing LLM response: {e}")
            # Fallback to default values
            complete_data = {
                'Category': item_data.get('Category', 'Unknown'),
                'Item': damage_item,
                'lifespan_years': 20,
                'price_type': 'Repair',
                'price_EUR': 1000,
                'unit': 'per piece',
                'source': 'fallback'
            }
    else:
        print("\nStep 2: Data complete from CSV, skipping LLM")
    
    # Step 3: Calculate upfront repair and maintenance schedule
    print("\nStep 3: Calculating upfront repair cost and maintenance schedule...")
    prompt = calculate_upfront_and_maintenance_prompt(damage_item, complete_data, severity)
    response = await call_ai_model(prompt, use_mock)
    
    try:
        cost_data = json.loads(response.strip().replace('```json', '').replace('```', ''))
        upfront = cost_data.get('upfront_repair', {})
        maintenance = cost_data.get('maintenance_schedule', [])
        
        print(f"✅ Upfront repair cost: {upfront.get('cost_EUR', 0)} EUR")
        print(f"   Description: {upfront.get('description', 'N/A')}")
        print(f"✅ Maintenance events scheduled: {len(maintenance)}")
        for maint in maintenance:
            print(f"   Year {maint.get('year')}: {maint.get('type')} - {maint.get('cost_EUR')} EUR")
    except json.JSONDecodeError as e:
        print(f"❌ Error parsing cost calculation response: {e}")
        # Fallback cost calculation
        base_cost = complete_data.get('price_EUR', 1000)
        severity_mult = {1: 0, 2: 1.3, 3: 1.7, 4: 2.3, 5: 3.0}.get(severity, 1.5)
        cost_data = {
            'upfront_repair': {
                'cost_EUR': base_cost * severity_mult if severity >= 2 else 0,
                'description': f'Repair/replacement of {damage_item}',
                'severity_multiplier': severity_mult,
                'includes_contingency': True
            },
            'maintenance_schedule': [],
            'reasoning': 'Fallback calculation due to parsing error'
        }
    
    # Step 4: Calculate 10-year cost table numerically
    print("\nStep 4: Calculating 10-year cost projection table...")
    ten_year_table = calculate_10year_projection(damage_item, cost_data, complete_data)
    print(f"✅ Upfront cost: {ten_year_table['upfront_cost']} EUR")
    print(f"✅ Total maintenance (10-year): {ten_year_table['total_maintenance_cost']} EUR")
    print(f"✅ Grand total (10-year): {ten_year_table['total_10year_cost']} EUR")
    
    return {
        'damage_item': damage_item,
        'severity': severity,
        'component_data': {
            'category': complete_data.get('Category'),
            'item': complete_data.get('Item'),
            'lifespan_years': complete_data.get('lifespan_years'),
            'base_price': complete_data.get('price_EUR'),
            'unit': complete_data.get('unit'),
            'data_source': complete_data.get('source', 'unknown')
        },
        'cost_breakdown': {
            'upfront_repair': cost_data.get('upfront_repair', {}),
            'maintenance_schedule': cost_data.get('maintenance_schedule', []),
            'reasoning': cost_data.get('reasoning', '')
        },
        'projection_10year': ten_year_table
    }



def print_cost_table(analysis_result: Dict):
    """Print a formatted 10-year cost table with upfront/maintenance split"""
    if not analysis_result:
        return
    
    print(f"\n{'='*80}")
    print(f"10-YEAR COST PROJECTION: {analysis_result['damage_item']}")
    print(f"Category: {analysis_result['component_data']['category']}")
    print(f"{'='*80}")
    
    # Print upfront cost
    upfront = analysis_result['cost_breakdown']['upfront_repair']
    print(f"\n{'UPFRONT REPAIR COST (Year 0)':^80}")
    print(f"{'-'*80}")
    print(f"Cost: {upfront.get('cost_EUR', 0):,.2f} EUR")
    print(f"Description: {upfront.get('description', 'N/A')}")
    print(f"Severity multiplier: {upfront.get('severity_multiplier', 1.0):.1f}x")
    
    # Print maintenance schedule
    print(f"\n{'MAINTENANCE SCHEDULE (Years 1-10)':^80}")
    print(f"{'-'*80}")
    table = analysis_result['projection_10year']['yearly_costs']
    if any(row['maintenance_cost'] > 0 for row in table):
        print(f"{'Year':<6} {'Work Description':<40} {'Cost (EUR)':<15} {'Cumulative (EUR)'}")
        print(f"{'-'*80}")
        for row in table:
            if row['maintenance_cost'] > 0:
                print(f"{row['year']:<6} {row['work_description']:<40} {row['maintenance_cost']:<15,.2f} {row['cumulative_cost']:<15,.2f}")
    else:
        print("No maintenance scheduled within 10 years")
    
    # Print summary
    proj = analysis_result['projection_10year']
    print(f"\n{'-'*80}")
    print(f"Upfront repair cost: {proj['upfront_cost']:,.2f} EUR ({proj['breakdown']['immediate_repair_pct']}%)")
    print(f"Total maintenance (10-year): {proj['total_maintenance_cost']:,.2f} EUR ({proj['breakdown']['ongoing_maintenance_pct']}%)")
    print(f"GRAND TOTAL (10-year): {proj['total_10year_cost']:,.2f} EUR")
    print(f"\n{proj['summary']}")
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
    Main function for API endpoint - analyzes multiple damage items and returns structured response.
    Now with clear upfront/maintenance cost separation.
    
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
        Dictionary with complete analysis results in API-ready format with upfront/maintenance split
    """
    # Default CSV path relative to backend directory
    if csv_path is None:
        csv_path = os.path.join(os.path.dirname(__file__), "..", "..", "dataset", "message.csv")
    
    # Create semaphore to limit concurrent API calls
    semaphore = asyncio.Semaphore(max_concurrent)
    
    async def analyze_with_semaphore(item: Dict) -> Dict:
        """Wrapper to use semaphore for rate limiting"""
        async with semaphore:
            return await analyze_damage(
                damage_item=item["item"],
                severity=item["severity"],
                csv_path=csv_path,
                use_mock=use_mock
            )
    
    # Create tasks with semaphore control
    tasks = [analyze_with_semaphore(item) for item in damage_items]
    
    # Run all analyses concurrently with rate limiting
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
    grand_total = sum(r['projection_10year']['total_10year_cost'] for r in successful_results)
    total_upfront = sum(r['projection_10year']['upfront_cost'] for r in successful_results)
    total_maintenance = sum(r['projection_10year']['total_maintenance_cost'] for r in successful_results)
    
    # Build response with clear cost separation
    response = {
        "status": "success",
        "timestamp": pd.Timestamp.now().isoformat(),
        "summary": {
            "total_items_analyzed": len(successful_results),
            "total_items_requested": len(damage_items),
            "failed_items_count": len(failed_items),
            "cost_breakdown": {
                "total_upfront_cost_EUR": round(total_upfront, 2),
                "total_maintenance_cost_EUR": round(total_maintenance, 2),
                "grand_total_10year_cost_EUR": round(grand_total, 2)
            },
            "cost_split_percentage": {
                "upfront_pct": round((total_upfront / grand_total * 100) if grand_total > 0 else 0, 1),
                "maintenance_pct": round((total_maintenance / grand_total * 100) if grand_total > 0 else 0, 1)
            }
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
    
    print("\nBUILDING DAMAGE ANALYSIS SYSTEM v2.0")
    print("="*80)
    print("NEW: Upfront repair costs vs. maintenance costs")
    print(f"Max concurrent analyses: {MAX_CONCURRENT}")
    print("="*80)
    
    # Test cases with different items and severities
    test_cases = [
        {
            "item": "Boiler",
            "severity": 5  # Critical - expect high upfront cost
        },
        {
            "item": "Thermostatic Radiator Valves",
            "severity": 3  # Moderate - some upfront, some maintenance
        },
        {
            "item": "Air Conditioning Units",
            "severity": 1  # Minimal - mostly maintenance only
        }
    ]
    
    # Run analyses using endpoint function
    response = asyncio.run(analyze_damages_for_endpoint(
        damage_items=test_cases,
        csv_path=CSV_PATH,
        use_mock=USE_MOCK,
        max_concurrent=MAX_CONCURRENT
    ))
    
    # Print summary with cost breakdown
    print(f"\n{'='*80}")
    print(f"ANALYSIS COMPLETE")
    print(f"{'='*80}")
    print(f"Status: {response['status']}")
    print(f"Items analyzed: {response['summary']['total_items_analyzed']}/{response['summary']['total_items_requested']}")
    print(f"\nCOST BREAKDOWN:")
    print(f"  Upfront repairs: {response['summary']['cost_breakdown']['total_upfront_cost_EUR']:,.2f} EUR ({response['summary']['cost_split_percentage']['upfront_pct']}%)")
    print(f"  10-year maintenance: {response['summary']['cost_breakdown']['total_maintenance_cost_EUR']:,.2f} EUR ({response['summary']['cost_split_percentage']['maintenance_pct']}%)")
    print(f"  GRAND TOTAL: {response['summary']['cost_breakdown']['grand_total_10year_cost_EUR']:,.2f} EUR")
    
    if response['failed_items']:
        print(f"\nWARNING: Failed items: {response['summary']['failed_items_count']}")
        for failed in response['failed_items']:
            print(f"   - {failed['item']}: {failed['error']}")
    
    print(f"\n{'='*80}")
    print("Individual Results:")
    print(f"{'='*80}")
    for analysis in response['analyses']:
        proj = analysis['projection_10year']
        print(f"\n{analysis['damage_item']} (Severity {analysis['severity']}/5):")
        print(f"  - Upfront: {proj['upfront_cost']:,.2f} EUR")
        print(f"  - Maintenance: {proj['total_maintenance_cost']:,.2f} EUR")
        print(f"  - Total: {proj['total_10year_cost']:,.2f} EUR")
    
    # Save complete response
    save_analysis_to_file(response, "api_response.json")
    
    print(f"\n{'='*80}")
    print("Analysis complete! Response saved to api_response.json")
    print(f"{'='*80}\n")
    
    # Print example JSON format for API documentation
    print("\nNEW API Response Format Example:")
    print("="*80)
    example_format = {
        "status": "success",
        "timestamp": "2025-11-29T10:30:00.123456",
        "summary": {
            "total_items_analyzed": 3,
            "total_items_requested": 3,
            "failed_items_count": 0,
            "cost_breakdown": {
                "total_upfront_cost_EUR": 8500.00,
                "total_maintenance_cost_EUR": 2150.00,
                "grand_total_10year_cost_EUR": 10650.00
            },
            "cost_split_percentage": {
                "upfront_pct": 79.8,
                "maintenance_pct": 20.2
            }
        },
        "analyses": [
            {
                "damage_item": "Boiler",
                "severity": 5,
                "component_data": {
                    "category": "Heating / Ventilation / Climate",
                    "item": "Boiler",
                    "lifespan_years": 20,
                    "base_price": 5000,
                    "unit": "per piece",
                    "data_source": "csv_direct"
                },
                "cost_breakdown": {
                    "upfront_repair": {
                        "cost_EUR": 7500,
                        "description": "Emergency replacement of critical boiler",
                        "severity_multiplier": 3.0,
                        "includes_contingency": True
                    },
                    "maintenance_schedule": [
                        {"year": 5, "type": "Inspection", "cost_EUR": 250, "description": "System inspection"},
                        {"year": 9, "type": "Minor maintenance", "cost_EUR": 400, "description": "Preventive service"}
                    ],
                    "reasoning": "Critical severity requires immediate replacement with 30-40% contingency"
                },
                "projection_10year": {
                    "upfront_cost": 7500.00,
                    "total_maintenance_cost": 750.00,
                    "total_10year_cost": 8250.00,
                    "year_0": {
                        "year": 0,
                        "upfront_cost": 7500.00,
                        "maintenance_cost": 0,
                        "total_cost": 7500.00,
                        "cumulative_cost": 7500.00,
                        "work_description": "Emergency replacement of critical boiler",
                        "is_upfront": True
                    },
                    "yearly_costs": [
                        # Years 1-10 with maintenance events
                    ],
                    "breakdown": {
                        "immediate_repair_pct": 90.9,
                        "ongoing_maintenance_pct": 9.1
                    }
                }
            }
            # ... more analyses
        ],
        "failed_items": None
    }
    print(json.dumps(example_format, indent=2))
    print("="*80)
