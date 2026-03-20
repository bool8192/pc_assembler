import os
import requests
import json
import psycopg2
from dotenv import load_dotenv
from smolagents import HfApiModel, CodeAgent, tool

load_dotenv()


@tool
def query_database(sql: str) -> str:
    """
    Query the PC components database to get prices, benchmarks and compatibility info.
    Args:
        sql: SQL SELECT query to execute.
    """
    conn = psycopg2.connect(os.getenv("SUPABASE_DB_URL"))
    cur = conn.cursor()
    cur.execute(sql)
    rows = cur.fetchall()
    cols = [desc[0] for desc in cur.description]
    conn.close()

    result = [", ".join(cols)]
    for row in rows:
        result.append(", ".join(str(v) for v in row))
    return "\n".join(result)

# Проверяем наличие ключей
hf_token = os.getenv("HF_TOKEN")
supabase_auth = os.getenv("SUPABASE_DB_URL")

if not hf_token:
    print("ОШИБКА: HF_TOKEN не найден")
    exit(1)
if not supabase_auth:
    print("ОШИБКА: supabase_db_url не найден")
    exit(1)


model = HfApiModel(
    model_id="meta-llama/Llama-4-Scout-17B-16E-Instruct",
    token=hf_token
)

tools = [
    query_database
]

system_prompt = """
#You are pc builder. You have an access to database with pc parts, consisting tables:
    gpus: id, model_id (FK → model_name), normalized_name, tdp, length_mm, power_connectors — конкретные модели видеокарт с техническими характеристиками.

    model_name: model_id, model_name, vram_gb — справочник маркетинговых названий GPU и объемов видеопамяти, джойнится к gpus и model_x_test по model_id.

    model_x_test: id, model_id (FK → model_name), test, resolution, preset, result — результаты бенчмарков и тестов производительности видеокарт в различных условиях.

    cpus: id, normalized_model_name, socket, tdp, compatible_chipsets_no_bios_update, compatible_chipsets_with_bios_update — подробные характеристики процессоров и их совместимость с чипсетами.

    cpu_x_test: id, cpu_id (FK → cpus), test, result — результаты тестирования производительности процессоров.

    coolers: id, normalized_name, tdp, compatible_sockets, height_mm, type — характеристики систем охлаждения, включая рассеиваемую мощность и совместимые сокеты.

    component_prices: id, component_type (enum), component_id, price_rub, is_available, source_url, manual_override, is_verified, created_at, updated_at — таблица цен на все типы комплектующих; component_id соответствует id из таблиц gpus, cpus или coolers в зависимости от типа.
    
    psus: id, normalized_name, wattage, cpu_pins_total, gpu_pins_total, form-factor, setrifical — блоки питания с указанием мощности, количества разъемов питания для процессора/видеокарты и сертификата эффективности.

    cases: id, normalized_name, supported_form_factors, max_cooler_height_mm, max_gpu_lenght_mm, puffability_tier — компьютерные корпуса с параметрами совместимости по габаритам кулера, видеокарты и форм-фактору материнских плат.

    storage: id, normalized_name, capacity_gb, type, interface, reliability_tier, speed_tier — накопители данных (SSD/HDD) с указанием объема, типа подключения и уровней производительности/надежности.

    motherboards: id, normalized_name, socket, chipset, form_factor, vrm_tier, ram_type, num_ram_slots, cpu_power_pins, required_cpu_power_pins — материнские платы с полным набором характеристик совместимости (сокет, чипсет, тип памяти, питание процессора).

    ram: id, normalized_name, total_capacity_gb, number_of_modules, speed_mhz, type — модули оперативной памяти с указанием общего объема, количества планок в комплекте и частоты.
    
# Constraints:
- Current Year: 2026.
- If information is not found after 3 search attempts, admit it and suggest alternative keywords.
- No fluff. Be objective, concise, and professional.
"""

agent = CodeAgent(
    tools=tools,
    model=model,
    max_steps=10,
    verbosity_level=2  # Показывает подробные логи
)

#agent.system_prompt = system_prompt
agent.default_summarizer_template = system_prompt


print("\n" + "="*60)

query = "Собери ПК за 130к для cyberpunk в 1440p"

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
