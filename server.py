import asyncio
import json
import uuid
from collections.abc import Generator

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel

from agent import (
    make_agent, make_model, get_available_tests,
    _parse_agent_output, supabase, RATIO, prompts
)

app = FastAPI()

# Хранилище запущенных задач
_jobs: dict[str, Generator] = {}

model_ll = make_model("hf")


# ─── Генератор — сердце всей системы ────────────────────────────────────────
# Обычная функция с yield вместо return.
# Каждый yield = одно SSE-сообщение в браузер.
# FastAPI сам поймёт что это стрим и будет отправлять по мере готовности.

def build_pipeline(query: str) -> Generator[str, None, None]:
    """
    Запускает агентов по очереди, после каждого yield'ит JSON-строку.
    Формат SSE: строка вида  data: {...}\n\n
    """

    def emit(event: str, payload: dict) -> str:
        # SSE-формат: event: <имя>\ndata: <json>\n\n
        return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"

    available_tests = get_available_tests()

    # ── 1. Init ───────────────────────────────────────────────────────────────
    try:
        agent_init = make_agent(model_ll, prompts["init"], name="init")
        request = _parse_agent_output(agent_init.run(query))
        yield emit("step", {
            "step": "init",
            "label": "Разбор запроса",
            "data": request
        })
    except Exception as e:
        yield emit("error", {"step": "init", "message": str(e)})
        return  # дальше нет смысла продолжать

    # Логика из твоего оригинала
    if request["resolution"] == 0:
        if   request["budget"] <= 110000: request["resolution"] = 1080
        elif request["budget"] > 210000:  request["resolution"] = 2160
        else:                             request["resolution"] = 1440

    budget = request["budget"]
    task   = request["task"]
    res    = request["resolution"]
    ddr    = "DDR4" if budget < 200000 else "DDR5"

    # ── 2. GPU ────────────────────────────────────────────────────────────────
    try:
        min_p, max_p = budget * RATIO["GPU"][0], budget * RATIO["GPU"][1]

        if task == "AI":
            agent_gpu = make_agent(model_ll, prompts["GPU_AI"], name="GPU_AI")
        else:
            # проверка наличия тестов — твоя логика
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

        gpu = _parse_agent_output(
            agent_gpu.run(f"min_price={min_p}, max_price={max_p}, target_task={task}, target_resolution={res}")
        )
        yield emit("step", {
            "step": "gpu",
            "label": "Видеокарта",
            "name": gpu.get("normalized_name"),
            "price": gpu.get("price_rub"),
        })
    except Exception as e:
        yield emit("error", {"step": "gpu", "message": str(e)})
        return

    # ── 3. CPU + MB ───────────────────────────────────────────────────────────
    try:
        min_p, max_p = budget * RATIO["CPU_MB"][0], budget * RATIO["CPU_MB"][1]
        agent_cpu_mb = make_agent(model_ll, prompts["CPU+MOTHERBOARD"], name="CPU+MB")
        cpu_mb = _parse_agent_output(
            agent_cpu_mb.run(f"min_price={min_p}, max_price={max_p}, target_task={task}, ram_type={ddr}")
        )
        yield emit("step", {
            "step": "cpu_mb",
            "label": "Процессор + Материнская плата",
            "cpu_name": cpu_mb.get("cpu_name"),
            "mb_name": cpu_mb.get("motherboard_name"),
            "price": cpu_mb.get("cpu_and_mb_price"),
        })
    except Exception as e:
        yield emit("error", {"step": "cpu_mb", "message": str(e)})
        return

    # ── 4. RAM ────────────────────────────────────────────────────────────────
    try:
        max_p = budget * RATIO["RAM"][1]
        agent_ram = make_agent(model_ll, prompts["RAM"], name="RAM")
        ram = _parse_agent_output(
            agent_ram.run(f"max_price={max_p}, ram_type={ddr}, target_task={query}")
        )
        yield emit("step", {
            "step": "ram",
            "label": "Оперативная память",
            "name": ram.get("normalized_name"),
            "price": ram.get("price_rub"),
        })
    except Exception as e:
        yield emit("error", {"step": "ram", "message": str(e)})
        return

    # ── 5. PSU ────────────────────────────────────────────────────────────────
    try:
        min_p, max_p = budget * RATIO["PSU"][0], budget * RATIO["PSU"][1]
        agent_psu = make_agent(model_ll, prompts["PSU"], name="PSU")
        psu = _parse_agent_output(agent_psu.run(
            f"min_price={min_p}, max_price={max_p}, "
            f"gpu_tdp={int(gpu['tdp'])}, cpu_tdp={int(cpu_mb['tdp'])}, "
            f"selected_mb_pins={int(cpu_mb['cpu_power_pins'])}, "
            f"selected_gpu_pins={int(gpu['power_connectors'])}"
        ))
        yield emit("step", {
            "step": "psu",
            "label": "Блок питания",
            "name": psu.get("normalized_name"),
            "price": psu.get("price_rub"),
        })
    except Exception as e:
        yield emit("error", {"step": "psu", "message": str(e)})
        return

    # ── 6. Storage ────────────────────────────────────────────────────────────
    try:
        min_p, max_p = budget * RATIO["STORAGE"][0], budget * RATIO["STORAGE"][1]
        min_cap = 240 if budget < 50000 else (1000 if budget > 15000 else 500)
        agent_disk = make_agent(model_ll, prompts["STORAGE"], name="STORAGE")
        disk = _parse_agent_output(
            agent_disk.run(f"min_price={min_p}, max_price={max_p}, min_capacity_gb={min_cap}")
        )
        yield emit("step", {
            "step": "storage",
            "label": "Накопитель",
            "name": disk.get("normalized_name"),
            "price": disk.get("price_rub"),
        })
    except Exception as e:
        yield emit("error", {"step": "storage", "message": str(e)})
        return

    # ── 7. Case ───────────────────────────────────────────────────────────────
    try:
        min_p, max_p = budget * RATIO["CASE"][0], budget * RATIO["CASE"][1]
        agent_case = make_agent(model_ll, prompts["CASE"], name="CASE")
        case = _parse_agent_output(agent_case.run(
            f"min_price={min_p}, max_price={max_p}, "
            f"motherboard_form_factor={cpu_mb['form_factor']}, "
            f"psu_form_factor={psu['form_factor']}, "
            f"selected_gpu_length={gpu['length_mm']}"
        ))
        yield emit("step", {
            "step": "case",
            "label": "🖥️ Корпус",
            "name": case.get("normalized_name"),
            "price": case.get("price_rub"),
        })
    except Exception as e:
        yield emit("error", {"step": "case", "message": str(e)})
        return

    # ── 8. Cooler ─────────────────────────────────────────────────────────────
    try:
        min_p, max_p = budget * RATIO["COOLER"][0], budget * RATIO["COOLER"][1]
        agent_cooler = make_agent(model_ll, prompts["COOLER"], name="COOLER")
        cooler = _parse_agent_output(agent_cooler.run(
            f"min_price={min_p}, max_price={max_p}, "
            f"selected_socket={cpu_mb['socket']}, "
            f"selected_cpu_tdp={cpu_mb['tdp']}, "
            f"selected_case_max_cooler_height={case['max_cooler_height_mm']}"
        ))
        yield emit("step", {
            "step": "cooler",
            "label": "Охлаждение",
            "name": cooler.get("normalized_name"),
            "price": cooler.get("price_rub"),
        })
    except Exception as e:
        yield emit("error", {"step": "cooler", "message": str(e)})
        return

    # ── Итог ──────────────────────────────────────────────────────────────────
    total = sum(filter(None, [
        gpu.get("price_rub"),
        cpu_mb.get("cpu_and_mb_price"),
        ram.get("price_rub"),
        psu.get("price_rub"),
        disk.get("price_rub"),
        case.get("price_rub"),
        cooler.get("price_rub"),
    ]))

    yield emit("done", {
        "budget": budget,
        "total": total,
        "components": [
            {"label": "Видеокарта",    "name": gpu.get("normalized_name"),      "price": gpu.get("price_rub")},
            {"label": "Процессор",     "name": cpu_mb.get("cpu_name"),          "price": None},
            {"label": "Материнская плата",     "name": cpu_mb.get("motherboard_name"),  "price": cpu_mb.get("cpu_and_mb_price"), "note": "цена за оба"},
            {"label": "ОЗУ",           "name": ram.get("normalized_name"),      "price": ram.get("price_rub")},
            {"label": "БП",            "name": psu.get("normalized_name"),      "price": psu.get("price_rub")},
            {"label": "Накопитель",    "name": disk.get("normalized_name"),     "price": disk.get("price_rub")},
            {"label": "Корпус",        "name": case.get("normalized_name"),     "price": case.get("price_rub")},
            {"label": "Охлаждение",    "name": cooler.get("normalized_name"),   "price": cooler.get("price_rub")},
        ]
    })


# ─── HTTP эндпоинты ──────────────────────────────────────────────────────────

class BuildRequest(BaseModel):
    query: str

@app.post("/start")
def start_build(req: BuildRequest):
    """
    Принимает запрос, создаёт job_id, сохраняет генератор.
    Возвращает job_id — браузер использует его для подписки на стрим.
    """
    job_id = str(uuid.uuid4())
    _jobs[job_id] = build_pipeline(req.query)
    return {"job_id": job_id}


@app.get("/stream/{job_id}")
def stream_build(job_id: str):
    """
    SSE-эндпоинт. Браузер подключается и получает события по мере готовности.
    media_type="text/event-stream" — это и есть SSE.
    """
    gen = _jobs.get(job_id)
    if gen is None:
        return {"error": "job not found"}

    def event_stream():
        try:
            yield from gen
        finally:
            # Чистим память после завершения
            _jobs.pop(job_id, None)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.get("/", response_class=HTMLResponse)
def index():
    """Отдаёт HTML-страницу. Никаких шаблонов — всё в одной строке."""
    return HTML  # см. ниже


# ─── HTML страница ────────────────────────────────────────────────────────────
# Весь фронтенд — одна строка. JavaScript прямо внутри.

HTML = """<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<title>PC Builder AI</title>
<style>
  body { font-family: sans-serif; max-width: 760px; margin: 60px auto; padding: 0 20px; color: #111; }
  h1   { font-size: 1.6rem; margin-bottom: 4px; }
  p.sub { color: #666; margin-top: 0; }
  textarea { width: 100%; padding: 10px; font-size: 1rem; border: 1px solid #ccc; border-radius: 6px; resize: vertical; }
  button { margin-top: 10px; padding: 10px 24px; background: #111; color: #fff; border: none; border-radius: 6px; font-size: 1rem; cursor: pointer; }
  button:disabled { background: #999; }

  #steps { margin-top: 32px; }

  .step-card {
    border: 1px solid #e0e0e0; border-radius: 8px;
    padding: 14px 18px; margin-bottom: 12px;
    animation: fadeIn 0.3s ease;
  }
  .step-card .label { font-weight: 600; font-size: 1rem; }
  .step-card .detail { color: #444; margin-top: 4px; font-size: 0.9rem; }
  .step-card .price { float: right; font-weight: 600; color: #2a7a2a; }

  .step-card.thinking {
    border-color: #f0c040; background: #fffbe6;
    color: #888;
  }

  #summary {
    margin-top: 28px; border: 2px solid #111; border-radius: 10px;
    padding: 20px 24px; display: none;
  }
  #summary h2 { margin-top: 0; }
  #summary table { width: 100%; border-collapse: collapse; }
  #summary td { padding: 7px 4px; border-bottom: 1px solid #eee; }
  #summary td:last-child { text-align: right; font-weight: 600; }
  #summary .total-row td { font-size: 1.1rem; font-weight: 700; border-top: 2px solid #111; border-bottom: none; }

  .err { color: #c0392b; font-size: 0.85rem; margin-top: 4px; }
  @keyframes fadeIn { from { opacity:0; transform:translateY(6px) } to { opacity:1; transform:none } }
</style>
</head>
<body>

<h1> PC Assembler AI</h1>
<p class="sub">Опишите задачи и бюджет — система подберёт комплектующие автоматически.</p>
<p class="sub">Примеры: <em>«собери ПК за 120тр для игр в 1440p»</em>, <em>«нужен комп за 80к для работы с видео»</em></p>

<textarea id="query" rows="3" placeholder="Ваш запрос..."></textarea>
<br>
<button id="btn" onclick="startBuild()">Подобрать комплектующие</button>

<div id="steps"></div>
<div id="summary"></div>

<script>
function fmt(price) {
  if (!price) return '—';
  return price.toLocaleString('ru-RU') + ' ₽';
}

async function startBuild() {
  const query = document.getElementById('query').value.trim();
  if (!query) return;

  document.getElementById('btn').disabled = true;
  document.getElementById('steps').innerHTML = '';
  document.getElementById('summary').style.display = 'none';

  // Шаг 1: POST /start — получаем job_id
  const res = await fetch('/start', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({query})
  });
  const {job_id} = await res.json();

  // Шаг 2: подписываемся на SSE-стрим
  // EventSource — встроенный браузерный API, никаких библиотек
  const es = new EventSource(`/stream/${job_id}`);

  // Каждый раз когда сервер yield'нул событие "step" — показываем карточку
  es.addEventListener('step', e => {
    const d = JSON.parse(e.data);
    addStepCard(d);
  });

  // Когда всё готово — показываем итоговую таблицу
  es.addEventListener('done', e => {
    const d = JSON.parse(e.data);
    showSummary(d);
    es.close();
    document.getElementById('btn').disabled = false;
  });

  es.addEventListener('error', e => {
    const d = JSON.parse(e.data);
    addErrorCard(d);
    es.close();
    document.getElementById('btn').disabled = false;
  });
}

function addStepCard(d) {
  const el = document.createElement('div');
  el.className = 'step-card';
  el.id = 'step-' + d.step;

  let detail = '';
  if (d.step === 'init') {
    detail = `Бюджет: ${fmt(d.data?.budget)} · Задача: ${d.data?.task} · Разрешение: ${d.data?.resolution}p`;
  } else if (d.step === 'cpu_mb') {
    detail = `${d.cpu_name} + ${d.mb_name}`;
  } else {
    detail = d.name || '';
  }

  const price = d.price ? `<span class="price">${fmt(d.price)}</span>` : '';

  el.innerHTML = `${price}<div class="label">${d.label}</div><div class="detail">${detail}</div>`;
  document.getElementById('steps').appendChild(el);
}

function addErrorCard(d) {
  const el = document.createElement('div');
  el.className = 'step-card';
  el.innerHTML = `<div class="label">⚠️ Ошибка на шаге ${d.step}</div><div class="err">${d.message}</div>`;
  document.getElementById('steps').appendChild(el);
}

function showSummary(d) {
  const rows = d.components
    .map(c => `<tr><td>${c.label}</td><td>${c.name || '—'}</td><td>${c.note ? '* ' : ''}${fmt(c.price)}</td></tr>`)
    .join('');

  const over = d.total > d.budget ? `<span style="color:#c0392b"> (+${fmt(d.total - d.budget)} сверху)</span>` : '';

  document.getElementById('summary').innerHTML = `
    <h2>Итоговая сборка</h2>
    <table>
      ${rows}
      <tr class="total-row">
        <td colspan="2">Итого</td>
        <td>${fmt(d.total)}${over}</td>
      </tr>
    </table>
    <p style="color:#888;font-size:0.8rem;margin-bottom:0">* CPU + MB — суммарная цена</p>
  `;
  document.getElementById('summary').style.display = 'block';
}
</script>
</body>
</html>"""

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)