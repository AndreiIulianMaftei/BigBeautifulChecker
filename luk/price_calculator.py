import panda as pd
from google_genai import GoogleGenAI
import os

def analysis_prompt(damage: str, damage_amount: int, period: int, price_database: database) -> str:
    return f"""
    You are an expert financial analyst. Provide a detailed analysis of the expected costs associated with {damage_amount} units of {damage_type} damage over a period of {period} years. Include potential repair costs, maintenance expenses, and any other relevant financial considerations.
    Your analysis should be comprehensive and consider various scenarios that could impact the overall costs. 
    Provide your response in a structured format with clear headings for each section of the analysis.

    Please take all the information reagriding the pricecs for each speific damage type from the following database: {price_database}
    """

def return_srtuctured_price(analysis: str, db: database) -> list:
    return f"""
    This is the analysis provided for the damage assessment:

    {analysis}

    Please return the final price for each type of damage in the {db} a structured JSON format with the following format:

    {{
        "breakdown": {{
            "repair_cost": float,
            "maintenance_expenses": float,
            "other_considerations": float
        }}
    }}

    Please make sure the names of the risks match those in the database provided.
    Please ensure that the JSON is properly formatted and valid. IF YOU FAIL TO RETURN THIS STRUCTURE PEOPLE WILL DIE.
    """

def generate_price_analysis(damage: str, damage_amount: int, period: int, price_database: database) -> str:
    prompt = analysis_prompt(damage, damage_amount, period, price_database)
    analysis = call_ai_model(prompt)  
    structured_price_prompt = return_srtuctured_price(analysis)
    final_price = call_ai_model(structured_price_prompt)  
    return final_price

def call_ai_model(prompt: str) -> str:
    api_key = os.getenv("GOOGLE_GENAI_API_KEY")
    client = GoogleGenAI(api_key=api_key)
    response = client.chat.completions.create(
        model="gemini-2.5-flash",
        messages=[
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": prompt}
        ]
    )
    return response.choices[0].message.content

def save_price_to_file(price_data: str, file_path: str) -> None:
    with open(file_path, 'w') as file:
        file.write(price_data)


if __name__ == "__main__":


    final_price = generate_price_analysis(damage_type, damage_amount, period, price_database)
    save_price_to_file(final_price, "final_price.json")