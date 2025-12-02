#!/usr/bin/env python3
"""
CSV Data Generator with LLM Support
This script meticulously fills in missing data in the property valuation CSV
using an LLM (OpenAI GPT) to provide reasonable estimates.
"""

import csv
import json
import os
import time
from dataclasses import dataclass
from typing import Optional
import google.generativeai as genai
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configuration
INPUT_CSV = "message.csv"
OUTPUT_CSV = "message_filled.csv"
BACKUP_CSV = "message_backup.csv"
PROGRESS_FILE = "fill_progress.json"

# Gemini Configuration
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
MODEL = "gemini-2.0-flash"  # Cost-effective and fast model
MAX_RETRIES = 3
RETRY_DELAY = 2  # seconds

@dataclass
class CSVRow:
    """Represents a row in the CSV file"""
    category: str
    item: str
    lifespan: str
    price_type: str
    price: str
    unit: str
    notes: str
    
    def has_missing_data(self) -> bool:
        """Check if this row has any missing data that needs to be filled"""
        # Check for missing values (represented as '-' or empty)
        missing_fields = []
        
        if self.lifespan in ['-', '', 'kU']:
            missing_fields.append('lifespan')
        if self.price_type in ['-', '']:
            missing_fields.append('price_type')
        if self.price in ['-', '']:
            missing_fields.append('price')
        if self.unit in ['-', '']:
            missing_fields.append('unit')
            
        return len(missing_fields) > 0
    
    def get_missing_fields(self) -> list:
        """Return list of missing fields"""
        missing = []
        if self.lifespan in ['-', '', 'kU']:
            missing.append('lifespan')
        if self.price_type in ['-', '']:
            missing.append('price_type')
        if self.price in ['-', '']:
            missing.append('price')
        if self.unit in ['-', '']:
            missing.append('unit')
        return missing
    
    def to_dict(self) -> dict:
        return {
            'category': self.category,
            'item': self.item,
            'lifespan': self.lifespan,
            'price_type': self.price_type,
            'price': self.price,
            'unit': self.unit,
            'notes': self.notes
        }
    
    def to_list(self) -> list:
        return [
            self.category,
            self.item,
            self.lifespan,
            self.price_type,
            self.price,
            self.unit,
            self.notes
        ]


class LLMDataGenerator:
    """Handles LLM interactions for generating missing data"""
    
    def __init__(self, api_key: str):
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel(MODEL)
    
    def generate_missing_data_batch(self, rows_with_context: list[tuple[CSVRow, list[CSVRow]]]) -> list[dict]:
        """
        Generate missing data for multiple rows in a single LLM call
        
        Args:
            rows_with_context: List of tuples (row, context_rows)
            
        Returns:
            List of dictionaries with filled values for each row
        """
        prompt = self._build_batch_prompt(rows_with_context)
        
        for attempt in range(MAX_RETRIES):
            try:
                system_prompt = """You are an expert in property valuation and building component pricing in Europe (EUR).
Your task is to provide realistic estimates for missing data in a property components database.

IMPORTANT GUIDELINES:
1. Prices should be in EUR and reflect European market averages (2024)
2. Lifespan should be in years (integer)
3. Price types are typically: "Replacement", "Repair", "New Coat", "Cleaning", etc.
4. Units are typically: "per piece", "per m²", "per m", "per step", "per sash", "per hole"
5. Be conservative with estimates - use middle-range market prices
6. Consider the category context when estimating

You must respond ONLY with a valid JSON array containing objects for each item, no additional text."""

                full_prompt = f"{system_prompt}\n\n{prompt}"
                
                response = self.model.generate_content(
                    full_prompt,
                    generation_config=genai.types.GenerationConfig(
                        temperature=0.3,
                        max_output_tokens=4000,
                    )
                )
                
                result = response.text.strip()
                
                # Parse JSON response
                # Handle potential markdown code blocks
                if result.startswith("```"):
                    result = result.split("```")[1]
                    if result.startswith("json"):
                        result = result[4:]
                    result = result.strip()
                
                parsed = json.loads(result)
                
                # Ensure we got a list
                if isinstance(parsed, dict):
                    parsed = [parsed]
                
                return parsed
                
            except json.JSONDecodeError as e:
                print(f"  JSON parse error (attempt {attempt + 1}): {e}")
                print(f"  Raw response: {result[:500]}...")
                if attempt < MAX_RETRIES - 1:
                    time.sleep(RETRY_DELAY)
            except Exception as e:
                print(f"  API/Unexpected error (attempt {attempt + 1}): {e}")
                if attempt < MAX_RETRIES - 1:
                    time.sleep(RETRY_DELAY)
        
        # Return defaults if all retries failed
        return [self._get_defaults(row, row.get_missing_fields()) for row, _ in rows_with_context]
    
    def _build_batch_prompt(self, rows_with_context: list[tuple[CSVRow, list[CSVRow]]]) -> str:
        """Build a prompt for multiple items at once"""
        
        items_text = []
        for idx, (row, context_rows) in enumerate(rows_with_context):
            missing_fields = row.get_missing_fields()
            context_str = self._build_context(context_rows)
            
            item_text = f"""
=== ITEM {idx + 1} ===
{context_str}

Category: {row.category}
Item: {row.item}
Current Lifespan: {row.lifespan} years
Current Price Type: {row.price_type}
Current Price: {row.price} EUR
Current Unit: {row.unit}
Notes: {row.notes}

Missing fields to estimate: {", ".join(missing_fields)}
"""
            items_text.append(item_text)
        
        return f"""
Please provide estimates for the following {len(rows_with_context)} items.

{chr(10).join(items_text)}

Respond with a JSON ARRAY containing {len(rows_with_context)} objects, one for each item in order.
Each object should contain ONLY the missing fields for that item.

Example response format:
[
  {{"item_index": 1, "lifespan": 20, "price_type": "Replacement", "price": 500, "unit": "per piece"}},
  {{"item_index": 2, "price": 300, "unit": "per m²"}},
  ...
]

Your response (JSON array only):
"""
        
    def generate_missing_data(self, row: CSVRow, context_rows: list[CSVRow]) -> dict:
        """
        Generate missing data for a single row using LLM (legacy method)
        
        Args:
            row: The row with missing data
            context_rows: Similar rows from the same category for context
            
        Returns:
            Dictionary with filled values
        """
        results = self.generate_missing_data_batch([(row, context_rows)])
        return results[0] if results else self._get_defaults(row, row.get_missing_fields())
    
    def _build_context(self, context_rows: list[CSVRow]) -> str:
        """Build context string from similar rows"""
        if not context_rows:
            return "No similar items available for context."
        
        context_lines = ["Similar items in the same category:"]
        for r in context_rows[:5]:  # Limit to 5 context rows
            context_lines.append(
                f"- {r.item}: Lifespan={r.lifespan} years, "
                f"Price Type={r.price_type}, Price={r.price} EUR, Unit={r.unit}"
            )
        return "\n".join(context_lines)
    
    def _build_prompt(self, row: CSVRow, missing_fields: list, context: str) -> str:
        """Build the prompt for the LLM"""
        
        existing_data = f"""
Category: {row.category}
Item: {row.item}
Current Lifespan: {row.lifespan} years
Current Price Type: {row.price_type}
Current Price: {row.price} EUR
Current Unit: {row.unit}
Notes: {row.notes}
"""
        
        fields_needed = ", ".join(missing_fields)
        
        # Build expected output format
        output_format = {}
        if 'lifespan' in missing_fields:
            output_format['lifespan'] = "integer (years)"
        if 'price_type' in missing_fields:
            output_format['price_type'] = "string (e.g., Replacement, Repair, New Coat)"
        if 'price' in missing_fields:
            output_format['price'] = "integer (EUR)"
        if 'unit' in missing_fields:
            output_format['unit'] = "string (e.g., per piece, per m², per m)"
            
        return f"""
{context}

Current item data:
{existing_data}

Missing fields that need to be estimated: {fields_needed}

Please provide realistic estimates for the missing fields.
Consider the item type, category, and any existing data when making estimates.

Respond with a JSON object containing ONLY the missing fields:
Example format: {json.dumps(output_format)}

Your response (JSON only):
"""
    
    def _get_defaults(self, row: CSVRow, missing_fields: list) -> dict:
        """Return default values when LLM fails"""
        defaults = {}
        
        if 'lifespan' in missing_fields:
            defaults['lifespan'] = 20  # Default lifespan
        if 'price_type' in missing_fields:
            defaults['price_type'] = "Replacement"
        if 'price' in missing_fields:
            defaults['price'] = 500  # Default price
        if 'unit' in missing_fields:
            defaults['unit'] = "per piece"
            
        return defaults


class CSVProcessor:
    """Main processor for the CSV file"""
    
    def __init__(self, input_file: str, output_file: str):
        self.input_file = input_file
        self.output_file = output_file
        self.rows: list[CSVRow] = []
        self.header: list[str] = []
        self.llm_generator: Optional[LLMDataGenerator] = None
        self.progress = {'processed': 0, 'filled': 0, 'errors': []}
        
    def load_csv(self):
        """Load the CSV file"""
        print(f"Loading CSV from {self.input_file}...")
        
        with open(self.input_file, 'r', encoding='utf-8') as f:
            reader = csv.reader(f)
            self.header = next(reader)
            
            for row in reader:
                if len(row) >= 7:
                    self.rows.append(CSVRow(
                        category=row[0],
                        item=row[1],
                        lifespan=row[2],
                        price_type=row[3],
                        price=row[4],
                        unit=row[5],
                        notes=row[6] if len(row) > 6 else ''
                    ))
                    
        print(f"Loaded {len(self.rows)} rows")
        
    def analyze_missing_data(self) -> dict:
        """Analyze and report on missing data"""
        stats = {
            'total_rows': len(self.rows),
            'rows_with_missing': 0,
            'missing_by_field': {
                'lifespan': 0,
                'price_type': 0,
                'price': 0,
                'unit': 0
            },
            'by_category': {}
        }
        
        for row in self.rows:
            if row.has_missing_data():
                stats['rows_with_missing'] += 1
                
                missing = row.get_missing_fields()
                for field in missing:
                    stats['missing_by_field'][field] += 1
                
                if row.category not in stats['by_category']:
                    stats['by_category'][row.category] = 0
                stats['by_category'][row.category] += 1
                
        return stats
    
    def get_context_rows(self, target_row: CSVRow) -> list[CSVRow]:
        """Get similar rows from the same category with complete data"""
        context = []
        for row in self.rows:
            if row.category == target_row.category and not row.has_missing_data():
                context.append(row)
        return context
    
    def fill_missing_data(self, use_llm: bool = True, batch_size: int = 10):
        """Fill in missing data"""
        
        if use_llm:
            if not GEMINI_API_KEY:
                print("ERROR: GEMINI_API_KEY not found in environment variables")
                print("Please set it in a .env file or export it")
                return
            self.llm_generator = LLMDataGenerator(GEMINI_API_KEY)
        
        # Load progress if exists
        self._load_progress()
        
        rows_to_process = []
        for i, row in enumerate(self.rows):
            if row.has_missing_data() and i >= self.progress['processed']:
                rows_to_process.append((i, row))
        
        total = len(rows_to_process)
        print(f"\nProcessing {total} rows with missing data in batches of {batch_size}...")
        print(f"This will require approximately {(total + batch_size - 1) // batch_size} API calls")
        print("-" * 60)
        
        for batch_start in range(0, total, batch_size):
            batch = rows_to_process[batch_start:batch_start + batch_size]
            batch_num = batch_start // batch_size + 1
            total_batches = (total + batch_size - 1) // batch_size
            
            print(f"\n{'='*60}")
            print(f"BATCH {batch_num}/{total_batches} - Processing {len(batch)} items")
            print(f"{'='*60}")
            
            # Print items in this batch
            for idx, (row_idx, row) in enumerate(batch):
                print(f"  [{idx+1}] {row.item[:60]}...")
                print(f"      Missing: {row.get_missing_fields()}")
            
            try:
                if use_llm:
                    # Prepare batch with context for each row
                    rows_with_context = []
                    for row_idx, row in batch:
                        context = self.get_context_rows(row)
                        rows_with_context.append((row, context))
                    
                    # Single API call for entire batch
                    print(f"\n  Calling Gemini API for {len(batch)} items...")
                    filled_data_list = self.llm_generator.generate_missing_data_batch(rows_with_context)
                    
                    # Apply results to each row
                    for idx, ((row_idx, row), filled_data) in enumerate(zip(batch, filled_data_list)):
                        # Remove item_index if present (it's just for tracking)
                        if 'item_index' in filled_data:
                            del filled_data['item_index']
                        
                        self._apply_filled_data(row, filled_data)
                        self.progress['filled'] += 1
                        print(f"  ✓ [{idx+1}] {row.item[:40]}... -> {filled_data}")
                else:
                    # Rule-based: process individually
                    for idx, (row_idx, row) in enumerate(batch):
                        filled_data = self._generate_rule_based(row)
                        self._apply_filled_data(row, filled_data)
                        self.progress['filled'] += 1
                        print(f"  ✓ [{idx+1}] {row.item[:40]}... -> {filled_data}")
                
                # Update progress to last row in batch
                self.progress['processed'] = batch[-1][0] + 1
                    
            except Exception as e:
                print(f"\n  ✗ Batch error: {e}")
                # Log errors for all items in the failed batch
                for row_idx, row in batch:
                    self.progress['errors'].append({
                        'row': row_idx,
                        'item': row.item,
                        'error': str(e)
                    })
                self.progress['processed'] = batch[-1][0] + 1
                
            # Save progress after each batch
            self._save_progress()
            print(f"\n--- Batch {batch_num} complete. Progress saved. ---")
            
            # Rate limiting between batches
            if use_llm and batch_start + batch_size < total:
                print("Waiting 2 seconds before next batch...")
                time.sleep(2)
    
    def _generate_rule_based(self, row: CSVRow) -> dict:
        """Generate data using rule-based logic (no LLM)"""
        result = {}
        missing = row.get_missing_fields()
        
        # Default rules based on category
        category_defaults = {
            'Heating / Ventilation / Climate': {'lifespan': 20, 'price': 800},
            'Central Hot Water Preparation': {'lifespan': 20, 'price': 600},
            'Chimney': {'lifespan': 20, 'price': 1000},
            'Building Envelope': {'lifespan': 30, 'price': 500},
            'Ceilings / Walls / Doors': {'lifespan': 25, 'price': 300},
            'Floor Coverings': {'lifespan': 20, 'price': 100},
            'Kitchen': {'lifespan': 15, 'price': 1000},
            'Bath / Shower / WC': {'lifespan': 20, 'price': 600},
            'TV and Radio Reception / Electrical Systems': {'lifespan': 20, 'price': 300},
            'Balconies / Sun Blinds / Conservatory': {'lifespan': 25, 'price': 800},
            'Basement and Attic Expansion': {'lifespan': 40, 'price': 2000},
            'Elevator': {'lifespan': 30, 'price': 5000},
            'Community Facilities': {'lifespan': 20, 'price': 500},
        }
        
        defaults = category_defaults.get(row.category, {'lifespan': 20, 'price': 500})
        
        if 'lifespan' in missing:
            result['lifespan'] = defaults['lifespan']
        if 'price_type' in missing:
            result['price_type'] = 'Replacement'
        if 'price' in missing:
            result['price'] = defaults['price']
        if 'unit' in missing:
            result['unit'] = 'per piece'
            
        return result
    
    def _apply_filled_data(self, row: CSVRow, data: dict):
        """Apply filled data to a row"""
        if 'lifespan' in data:
            row.lifespan = str(data['lifespan'])
        if 'price_type' in data:
            row.price_type = str(data['price_type'])
        if 'price' in data:
            row.price = str(data['price'])
        if 'unit' in data:
            row.unit = str(data['unit'])
    
    def save_csv(self):
        """Save the processed CSV"""
        print(f"\nSaving to {self.output_file}...")
        
        with open(self.output_file, 'w', encoding='utf-8', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(self.header)
            
            for row in self.rows:
                writer.writerow(row.to_list())
                
        print(f"Saved {len(self.rows)} rows")
    
    def backup_original(self):
        """Create a backup of the original file"""
        import shutil
        backup_path = self.input_file.replace('.csv', '_backup.csv')
        shutil.copy(self.input_file, backup_path)
        print(f"Backup created: {backup_path}")
    
    def _save_progress(self):
        """Save progress to file"""
        with open(PROGRESS_FILE, 'w') as f:
            json.dump(self.progress, f, indent=2)
    
    def _load_progress(self):
        """Load progress from file if exists"""
        if os.path.exists(PROGRESS_FILE):
            with open(PROGRESS_FILE, 'r') as f:
                self.progress = json.load(f)
            print(f"Resuming from row {self.progress['processed']}")
    
    def print_report(self):
        """Print final report"""
        print("\n" + "=" * 60)
        print("PROCESSING REPORT")
        print("=" * 60)
        print(f"Total rows processed: {self.progress['processed']}")
        print(f"Rows filled successfully: {self.progress['filled']}")
        print(f"Errors encountered: {len(self.progress['errors'])}")
        
        if self.progress['errors']:
            print("\nErrors:")
            for err in self.progress['errors'][:10]:  # Show first 10 errors
                print(f"  - Row {err['row']}: {err['item'][:40]}... - {err['error']}")
            if len(self.progress['errors']) > 10:
                print(f"  ... and {len(self.progress['errors']) - 10} more errors")


def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Fill missing CSV data using LLM')
    parser.add_argument('--input', '-i', default=INPUT_CSV, help='Input CSV file')
    parser.add_argument('--output', '-o', default=OUTPUT_CSV, help='Output CSV file')
    parser.add_argument('--no-llm', action='store_true', help='Use rule-based filling instead of LLM')
    parser.add_argument('--analyze-only', action='store_true', help='Only analyze missing data')
    parser.add_argument('--batch-size', type=int, default=10, help='Batch size for processing')
    parser.add_argument('--reset', action='store_true', help='Reset progress and start fresh')
    
    args = parser.parse_args()
    
    # Reset progress if requested
    if args.reset and os.path.exists(PROGRESS_FILE):
        os.remove(PROGRESS_FILE)
        print("Progress reset")
    
    processor = CSVProcessor(args.input, args.output)
    processor.load_csv()
    
    # Analyze missing data
    stats = processor.analyze_missing_data()
    
    print("\n" + "=" * 60)
    print("MISSING DATA ANALYSIS")
    print("=" * 60)
    print(f"Total rows: {stats['total_rows']}")
    print(f"Rows with missing data: {stats['rows_with_missing']}")
    print(f"\nMissing by field:")
    for field, count in stats['missing_by_field'].items():
        print(f"  {field}: {count}")
    print(f"\nMissing by category:")
    for cat, count in sorted(stats['by_category'].items(), key=lambda x: x[1], reverse=True):
        print(f"  {cat}: {count}")
    
    if args.analyze_only:
        return
    
    # Confirm before processing
    print("\n" + "-" * 60)
    if not args.no_llm:
        print("This will use the Google Gemini API to fill missing data.")
        print("Make sure GEMINI_API_KEY is set in your environment.")
    else:
        print("Using rule-based filling (no LLM)")
    
    response = input("\nProceed? (y/n): ").strip().lower()
    if response != 'y':
        print("Aborted")
        return
    
    # Create backup
    processor.backup_original()
    
    # Fill missing data
    processor.fill_missing_data(use_llm=not args.no_llm, batch_size=args.batch_size)
    
    # Save results
    processor.save_csv()
    
    # Print report
    processor.print_report()
    
    print(f"\nDone! Output saved to: {args.output}")


if __name__ == "__main__":
    main()
