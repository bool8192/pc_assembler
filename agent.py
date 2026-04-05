import os
import requests
import json
import psycopg2
from dotenv import load_dotenv
#from smolagents import HfApiModel, CodeAgent, tool
from smolagents import CodeAgent, tool, InferenceClientModel, LiteLLMModel, OpenAIServerModel
from urllib.parse import urlparse, urlunparse
load_dotenv()

import litellm
litellm._turn_on_debug()

raw_url = os.getenv("SUPABASE_DB_URL")
parsed = urlparse(raw_url)
clean_url = urlunparse(parsed._replace(query=""))

conn = psycopg2.connect(clean_url, sslmode="require", prepare_threshold=None)


from supabase import create_client
import os

url = "https://xfechilbgyguxktyrzye.supabase.co"
key = "sb_publishable_pn5iduO40DF0W_kpBGj34g_N0H7va_G"
supabase = create_client(url, key)

@tool
def query_database(sql: str) -> str:
    """
    Query the PC components database to get prices, benchmarks and compatibility info.
    Args:
        sql: SQL SELECT query to execute.
    """
    try:
        clean_sql = sql.strip().rstrip(";")  # убираем ; если есть
        response = supabase.rpc("run_query", {"sql": clean_sql}).execute()
        return str(response.data)
    except Exception as e:
        return f"Database Error: {str(e)}"

# Проверяем наличие ключей
hf_token = os.getenv("HF_TOKEN")
supabase_auth = os.getenv("SUPABASE_DB_URL")

if not hf_token:
    print("ОШИБКА: HF_TOKEN не найден")
    exit(1)
if not supabase_auth:
    print("ОШИБКА: supabase_db_url не найден")
    exit(1)


#model = InferenceClientModel(
#    model_id="meta-llama/Llama-4-Scout-17B-16E-Instruct",
#    token=hf_token
#)

model = OpenAIServerModel(
    model_id="llama-3.3-70b-versatile",
    api_base="https://api.groq.com/openai/v1",
    api_key=os.getenv("GROQ_API_KEY")
)

tools = [
    query_database
]

system_prompt = """
#You are pc builder.
 # CRITICAL OPERATIONAL RULES:
1. **NO HALLUCINATIONS**: You are FORBIDDEN from using your internal knowledge to suggest PC parts or prices. Everything MUST come from the provided SQL database.
2. **STRICT SCHEMA ADHERENCE**: Use ONLY the tables and columns defined below (gpus, cpus, motherboards, etc.).
3. **TOOL-FIRST POLICY**: If a database query fails, DO NOT proceed with estimated values. Report the specific error and attempt to fix the SQL query ONCE. If it fails again, TERMINATE and ask for technical assistance.
4. **NO AGED DATA**: Never suggest components based on your training data (e.g., RTX 30-series or Ryzen 5000) unless they are explicitly found in the current Database with 'is_available = TRUE'.
 You have an access to database with pc parts you have to use only this database, consisting tables:

# DATABASE SCHEMA (READ-ONLY):
- gpus: id, model_id (FK → model_name), normalized_name, tdp, length_mm, power_connectors
- model_name: model_id, model_name, vram_gb
- model_x_test: id, model_id (FK → model_name), test, resolution, preset, result
- cpus: id, normalized_model_name, socket, tdp, compatible_chipsets_no_bios_update, compatible_chipsets_with_bios_update
- cpu_x_test: id, cpu_id (FK → cpus), test, result
- coolers: id, normalized_name, tdp, compatible_sockets, height_mm, type
- component_prices: id, component_type (enum), component_id, price_rub, is_available, is_verified
- psus: id, normalized_name, wattage, cpu_pins_total, gpu_pins_total, form-factor, setrificate
- cases: id, normalized_name, supported_form_factors, max_cooler_height_mm, max_gpu_lenght_mm, puffability_tier
- storage: id, normalized_name, capacity_gb, type, interface, reliability_tier, speed_tier
- motherboards: id, normalized_name, socket, chipset, form_factor, vrm_tier, ram_type, num_ram_slots, cpu_power_pins, required_cpu_power_pins
- ram: id, normalized_name, total_capacity_gb, number_of_modules, speed_mhz, type
    
NEVER use phrases like 'Let's assume' or 'Suppose we got'. If you don't have real data from the tool, the build is FAILED.
    
1. CORE ALGORITHM (The "Residual Budget" Rule)

    Initialize: Set X=Initial Budget.

    GPU First: Allocate a portion of X for the GPU. Find the GPU. Update X=X−PriceGPU.

    Sequential Selection: For every subsequent component (CPU+MB, RAM, etc.), recalculate boundaries based on the remaining X.

    Tolerance: Final total must be within ±5−10% of the initial budget. If a range is provided, stay within that range.
    
    NEVER USE LIMIT IN QUERIES

2. COMPONENT SELECTION & SQL TEMPLATES
STEP 1: GPU

Rule: Select GPU based on task and budget. If model_x_test lacks data for a specific card, join model_name with model_x_test to estimate performance from similar models.
TEMPLATE:
SELECT g.*, p.price_rub, mxt.test, mxt.result
FROM gpus as g 
INNER JOIN component_prices as p ON p.component_id = g.id 
  AND p.is_available = TRUE AND p.is_verified = TRUE 
  AND p.price_rub BETWEEN {min_price} AND {max_price} 
INNER JOIN model_x_test as mxt ON mxt.model_id = g.model_id
ORDER BY normalized_name, price_rub
LIMIT 8000;

STEP 2: CPU + MOTHERBOARD

Rule: If benchmark or test is missing, join cpus with cpu_x_test to estimate.
TEMPLATE:
WITH cpu_x_test_prices AS (
  SELECT c.normalized_model_name, t.test, t.result, p.price_rub,
    CASE WHEN c.tdp < 70 THEN 'low' WHEN c.tdp >= 70 AND c.tdp < 121 THEN 'mid' ELSE 'high' END AS tdp_tier,
    c.socket, c.compatible_chipsets_no_bios_flash
  FROM cpu_x_test AS t 
  INNER JOIN cpus AS c ON c.id = t.cpu_id 
  INNER JOIN component_prices AS p ON c.id = p.component_id AND p.is_available = TRUE AND p.is_verified = TRUE
),
motherboard_prices AS (
  SELECT m.normalized_name, m.socket, m.chipset, m.vrm_tier, m.form_factor, m.ram_type, m.num_ram_slots, m.cpu_power_pins, m.required_cpu_power_pins, p.price_rub AS mb_price
  FROM motherboards AS m 
  INNER JOIN component_prices AS p ON m.id = p.component_id AND p.is_available = TRUE AND p.is_verified = TRUE
)
SELECT c.normalized_model_name AS cpu_name, m.normalized_name AS motherboard_name, c.test, c.result, 
       c.price_rub + m.mb_price AS cpu_and_mb_price, m.form_factor, m.ram_type, m.num_ram_slots, m.cpu_power_pins, m.required_cpu_power_pins
FROM cpu_x_test_prices AS c
INNER JOIN motherboard_prices AS m ON c.socket = m.socket 
  AND m.chipset = ANY(c.compatible_chipsets_no_bios_flash) 
  AND m.vrm_tier = c.tdp_tier
ORDER BY cpu_name, motherboard_name;

STEP 3: RAM

Rule: Must match ram_type of the chosen Motherboard. Consider that buying 2 single modules might be cheaper than a 2-module kit.

SELECT r.*, p.price_rub 
FROM ram AS r 
INNER JOIN component_prices AS p ON r.id = p.component_id 
WHERE r.type = {selected_mb_ram_type} 
  AND p.price_rub <= {remaining_ram_budget};

STEP 4: PSU

Rule: Calculation: wattage >= 1.5 * (gpu_tdp + cpu_tdp) + 50. Ensure cpu_pins_total >= motherboards.cpu_power_pins.

SELECT ps.*, p.price_rub 
FROM psus AS ps 
INNER JOIN component_prices AS p ON ps.id = p.component_id 
WHERE ps.cpu_pins_total >= {selected_mb_pins} 
  AND ps.wattage >= {calculated_wattage} 
  AND p.price_rub BETWEEN {min} AND {max};

STEP 5: STORAGE
TEMPLATE:
SELECT s.*, p.price_rub
FROM storage AS s
INNER JOIN component_prices AS p ON s.id = p.component_id 
  AND p.is_available = TRUE 
  AND p.price_rub <= {remaining_storage_budget}
WHERE s.type = 'SSD' -- Or 'HDD' if requested
  AND s.capacity_gb >= {min_capacity}
ORDER BY p.price_rub;

STEP 6: CASE
TEMPLATE:
SELECT c.*, p.price_rub
FROM cases AS c
INNER JOIN component_prices AS p ON c.id = p.component_id 
  AND p.is_available = TRUE 
  AND p.price_rub <= {remaining_case_budget}
WHERE c.supported_form_factors in (...)
  AND c.max_gpu_lenght_mm >= {selected_gpu_length}
ORDER BY c.puffability_tier DESC, p.price_rub ASC;

STEP 7: COOLER
TEMPLATE:
SELECT cl.*, p.price_rub
FROM coolers AS cl
INNER JOIN component_prices AS p ON cl.id = p.component_id 
  AND p.is_available = TRUE 
  AND p.price_rub <= {remaining_cooler_budget}
WHERE cl.compatible_sockets in ()
  AND cl.tdp >= ({selected_cpu_tdp} * 1.5)
  AND cl.height_mm <= {selected_case_max_cooler_height}
ORDER BY cl.tdp DESC, p.price_rub ASC;



3. OUTPUT REQUIREMENTS

    Present the final build as a list.

    Show the price for each component.

    Display the Remaining Budget calculation after each major step.

    No conversational filler. Only technical data and final assembly.
    
    Output language = input language
"""

query = "Собери ПК за 130к для cyberpunk в 1440p"



agent = CodeAgent(
    tools=tools,
    model=model,
    step_callbacks=[lambda x: __import__('time').sleep(2)],
    max_steps=23,
    verbosity_level=2
)
# Формируем полный запрос, где правила идут ПЕРВЫМИ
full_query = f"{system_prompt}\n\nUSER_REQUEST: {query}"

print(f"\n❓ Запуск сборки: {query}\n")

try:
    # Запускаем склеенный текст
    result = agent.run(full_query)
    print("\n✅ РЕЗУЛЬТАТ:")
    print(result)
except Exception as e:
    print(f"\n❌ Ошибка исполнения: {e}")

#agent.system_prompt = system_prompt
#agent.default_summarizer_template = system_prompt

print("\n" + "="*60)

print(f"\n❓ Вопрос: {query}\n")

try:
    result = agent.run(query)
    print("\n" + "="*60)
    print("✅ РЕЗУЛЬТАТ:")
    print("="*60)
    print(result)
    
except Exception as e:
    print(f"\n❌ Ошибка: {e}")
    import traceback
    traceback.print_exc()
