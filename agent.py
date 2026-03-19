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

if not hf_token:
    print("ОШИБКА: HF_TOKEN не найден")
    exit(1)

model = HfApiModel(
    model_id="meta-llama/Llama-4-Scout-17B-16E-Instruct",
    token=hf_token
)

tools = [
    query_database
]

system_prompt = """

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
