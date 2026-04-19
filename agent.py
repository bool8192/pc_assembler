# ── stdlib ────────────────────────────────────────────────────────────────────
import ast
import json
import logging
import time

# ── third-party ───────────────────────────────────────────────────────────────
import litellm
from dotenv import load_dotenv
from smolagents import CodeAgent, InferenceClientModel, OpenAIModel, tool
from supabase import create_client

# ── local ─────────────────────────────────────────────────────────────────────
from prompt import prompts

# ── env ───────────────────────────────────────────────────────────────────────

import os
from dotenv import load_dotenv
dotenv_path = os.path.join(os.path.dirname(__file__), ".env")

# ← вот тут грузим явно
loaded = load_dotenv(dotenv_path, override=True, verbose=True)
litellm.set_debug = False

# ── logging: агентское "говнище" → файл, stdout остаётся чистым ───────────────
LOG_FILE = "agent_debug.log"

def _setup_logger() -> logging.Logger:
    logger = logging.getLogger("agent_debug")
    logger.setLevel(logging.DEBUG)
    fh = logging.FileHandler(LOG_FILE, mode="w", encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s  %(message)s"))
    logger.addHandler(fh)
    logger.propagate = False
    return logger

_log = _setup_logger()

# Smolagents пишет через rich напрямую в stdout — перехватываем на уровне
# step_callback: каждый шаг агента дополнительно логируем в файл.
# verbosity_level=0 глушит rich-вывод; шаги всё равно попадают в колбэк.
def _make_step_callback(agent_name: str):
    def callback(step_log) -> None:
        _log.debug("[%s] %s", agent_name, step_log)
        time.sleep(2.5)          # rate-limit пауза — была в оригинале
    return callback

# ── supabase ──────────────────────────────────────────────────────────────────
_hf_token      = os.getenv("HF_TOKEN")
print(_hf_token)
_supabase_url  = os.getenv("url")
_supabase_key  = os.getenv("key")

if not _hf_token:
    raise RuntimeError("HF_TOKEN не найден в .env")
if not _supabase_url or not _supabase_key:
    raise RuntimeError("url / key для Supabase не найдены в .env")

supabase = create_client(_supabase_url, _supabase_key)

# ── database tool ─────────────────────────────────────────────────────────────
@tool
def query_database(sql: str) -> str:
    """
    Query the PC components database to get prices, benchmarks and compatibility info.
    Args:
        sql: SQL SELECT query to execute (no semicolons).
    """
    try:
        clean_sql = sql.strip().rstrip(";")
        response = supabase.rpc("run_query", {"sql": clean_sql}).execute()
        return json.dumps(response.data, ensure_ascii=False, indent=2) if response.data else "[]"
    except Exception as e:
        return f"Database Error: {e}"

# ── helpers ───────────────────────────────────────────────────────────────────
def get_available_tests() -> list[str]:
    try:
        response = supabase.rpc("run_query", {"sql": "SELECT distinct(test) FROM model_x_test"}).execute()
        return [row["test"] for row in response.data] if response.data else []
    except Exception:
        return ["Relative Performance TechPowerUp"]

def _parse_agent_output(raw) -> dict | str:
    """Пробует привести ответ агента к dict; если не выходит — возвращает как есть."""
    if isinstance(raw, dict):
        return raw
    clean = str(raw).replace("Final answer:", "").strip()
    try:
        return ast.literal_eval(clean)
    except (ValueError, SyntaxError):
        return clean

# ── model / agent factories ───────────────────────────────────────────────────
def make_model(provider: str):
    match provider:
        case "hf" | "huggingface":
            return InferenceClientModel(
                model_id="meta-llama/Llama-4-Scout-17B-16E-Instruct",
                token=_hf_token,
            )
        case "groq":
            return OpenAIModel(
                model_id="llama-3.3-70b-versatile",
                api_base="https://api.groq.com/openai/v1",
                api_key=os.getenv("GROQ_API_KEY"),
            )
        case "google":
            return OpenAIModel(
                model_id="gemini-2.0-flash",
                api_base="https://generativelanguage.googleapis.com/v1beta/openai/",
                api_key=os.getenv("GOOGLE_API_KEY"),
            )
        case _:
            raise ValueError(f"Неизвестный провайдер: {provider}")

def make_agent(model, sys_prompt: str, name: str, max_steps: int = 8) -> CodeAgent:
    return CodeAgent(
        tools=[query_database],
        model=model,
        code_block_tags=("```python", "```"),
        additional_authorized_imports=["json", "re", "pandas"],
        instructions=sys_prompt,
        step_callbacks=[_make_step_callback(name)],
        max_steps=max_steps,
        verbosity_level=0,          # rich-вывод заглушён; логи идут в файл
    )

# бюджетные доли: [min, max] для каждого компонента
RATIO = {
    "GPU":      [0.38, 0.51],
    "CPU_MB":   [0.14, 0.22],
    "RAM":      [0.10, 0.16],
    "PSU":      [0.04, 0.08],
    "STORAGE":  [0.08, 0.16],
    "CASE":     [0.02, 0.06],
    "COOLER":   [0.01, 0.04],
}


if __name__ == "__main__":
    # ── main flow ─────────────────────────────────────────────────────────────────
    available_tests = get_available_tests()
    model_ll = make_model("hf")

    # ── 1. init-агент: парсим запрос ──────────────────────────────────────────────
    agent_init = make_agent(model_ll, prompts["init"], name="init")
    try:
        request = _parse_agent_output(agent_init.run(query))
        print(f"✓ Init: {request}")
    except Exception as e:
        raise RuntimeError(f"Init-агент упал: {e}")

    if request["resolution"] == 0:
        if   request["budget"] <= 110000: request["resolution"] = 1080
        elif request["budget"] > 210000:  request["resolution"] = 2160
        else:                             request["resolution"] = 1440

    budget = request["budget"]
    task   = request["task"]
    res    = request["resolution"]
    ddr    = "DDR4" if budget < 200000 else "DDR5"

    # ── 2. GPU ────────────────────────────────────────────────────────────────────
    min_p, max_p = budget * RATIO["GPU"][0], budget * RATIO["GPU"][1]

    if task == "AI":
        agent_gpu = make_agent(model_ll, prompts["GPU_AI"], name="GPU_AI")
        gpu_input = f"min_price={min_p}, max_price={max_p}, target_task={task}, target_resolution={res}"
        gpu = _parse_agent_output(agent_gpu.run(gpu_input))
    else:
        cnt_sql = (
            f"SELECT COUNT(*) FROM gpus g "
            f"INNER JOIN component_prices p ON p.component_id = g.id "
            f"AND p.is_available=TRUE AND p.is_verified=TRUE "
            f"AND p.price_rub BETWEEN {min_p} AND {max_p} "
            f"INNER JOIN model_x_test mxt ON mxt.model_id = g.model_id "
            f"AND mxt.test='{task}' AND mxt.resolution='{res}'"
        )
        cnt_resp = supabase.rpc("run_query", {"sql": cnt_sql}).execute()
        if not cnt_resp.data or cnt_resp.data[0].get("count", 0) == 0:
            task = "Relative Performance TechPowerUp"

        agent_gpu = make_agent(model_ll, prompts["GPU"], name="GPU")
        gpu_input = f"min_price={min_p}, max_price={max_p}, target_task={task}, target_resolution={res}"
        gpu = _parse_agent_output(agent_gpu.run(gpu_input))

    print(f"✓ GPU:     {gpu.get('normalized_name')}  —  {gpu.get('price_rub')} ₽")

    # ── 3. CPU + Motherboard ──────────────────────────────────────────────────────
    min_p, max_p = budget * RATIO["CPU_MB"][0], budget * RATIO["CPU_MB"][1]
    agent_cpu_mb = make_agent(model_ll, prompts["CPU+MOTHERBOARD"], name="CPU+MB")
    cpu_mb = _parse_agent_output(
        agent_cpu_mb.run(f"min_price={min_p}, max_price={max_p}, target_task={task}, ram_type={ddr}")
    )
    print(f"✓ CPU:     {cpu_mb.get('cpu_name')}")
    print(f"  MB:      {cpu_mb.get('motherboard_name')}  —  {cpu_mb.get('cpu_and_mb_price')} ₽")

    # ── 4. RAM ────────────────────────────────────────────────────────────────────
    max_p = budget * RATIO["RAM"][1]
    agent_ram = make_agent(model_ll, prompts["RAM"], name="RAM")
    ram = _parse_agent_output(
        agent_ram.run(f"max_price={max_p}, ram_type={ddr}, target_task={query}")
    )
    print(f"✓ RAM:     {ram.get('normalized_name')}  —  {ram.get('price_rub')} ₽")

    # ── 5. PSU ────────────────────────────────────────────────────────────────────
    min_p, max_p = budget * RATIO["PSU"][0], budget * RATIO["PSU"][1]
    agent_psu = make_agent(model_ll, prompts["PSU"], name="PSU")
    psu = _parse_agent_output(agent_psu.run(
        f"min_price={min_p}, max_price={max_p}, "
        f"gpu_tdp={int(gpu['tdp'])}, cpu_tdp={int(cpu_mb['tdp'])}, "
        f"selected_mb_pins={int(cpu_mb['cpu_power_pins'])}, "
        f"selected_gpu_pins={int(gpu['power_connectors'])}"
    ))
    print(f"✓ PSU:     {psu.get('normalized_name')}  —  {psu.get('price_rub')} ₽")

    # ── 6. Storage ────────────────────────────────────────────────────────────────
    min_p, max_p = budget * RATIO["STORAGE"][0], budget * RATIO["STORAGE"][1]
    min_cap = 240 if budget < 50000 else (1000 if budget > 15000 else 500)
    agent_disk = make_agent(model_ll, prompts["STORAGE"], name="STORAGE")
    disk = _parse_agent_output(
        agent_disk.run(f"min_price={min_p}, max_price={max_p}, min_capacity_gb={min_cap}")
    )
    print(f"✓ Storage: {disk.get('normalized_name')}  —  {disk.get('price_rub')} ₽")

    # ── 7. Case ───────────────────────────────────────────────────────────────────
    min_p, max_p = budget * RATIO["CASE"][0], budget * RATIO["CASE"][1]
    agent_case = make_agent(model_ll, prompts["CASE"], name="CASE")
    case = _parse_agent_output(agent_case.run(
        f"min_price={min_p}, max_price={max_p}, "
        f"motherboard_form_factor={cpu_mb['form_factor']}, "
        f"psu_form_factor={psu['form_factor']}, "
        f"selected_gpu_length={gpu['length_mm']}"
    ))
    print(f"✓ Case:    {case.get('normalized_name')}  —  {case.get('price_rub')} ₽")

    # ── 8. Cooler ─────────────────────────────────────────────────────────────────
    min_p, max_p = budget * RATIO["COOLER"][0], budget * RATIO["COOLER"][1]
    agent_cooler = make_agent(model_ll, prompts["COOLER"], name="COOLER")
    cooler = _parse_agent_output(agent_cooler.run(
        f"min_price={min_p}, max_price={max_p}, "
        f"selected_socket={cpu_mb['socket']}, "
        f"selected_cpu_tdp={cpu_mb['tdp']}, "
        f"selected_case_max_cooler_height={case['max_cooler_height_mm']}"
    ))
    print(f"✓ Cooler:  {cooler.get('normalized_name')}  —  {cooler.get('price_rub')} ₽")

    # ── итого ─────────────────────────────────────────────────────────────────────
    total = sum(filter(None, [
        gpu.get("price_rub"),
        cpu_mb.get("cpu_and_mb_price"),
        ram.get("price_rub"),
        psu.get("price_rub"),
        disk.get("price_rub"),
        case.get("price_rub"),
        cooler.get("price_rub"),
    ]))
    print(f"\n{'─'*45}")
    print(f"  Итого: ~{total:,} ₽  (бюджет: {budget:,} ₽)".replace(",", " "))
    print(f"{'─'*45}")
