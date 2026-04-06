# PC Assembler Agent

AI-агент для подбора оптимальной сборки ПК по бюджету и целевым задачам. Агент сам выбирает комплектующие, проверяет совместимость и возвращает готовую сборку со ссылками на Wildberries.

---

## Как это работает

Пользователь вводит запрос в свободной форме:

```
собери ПК за 120тр для киберпанк и кс2
```

Дальше агент работает самостоятельно:

1. **Init-агент** — парсит запрос, определяет бюджет, целевое разрешение и задачи
2. **Специализированные агенты** — каждый подбирает один компонент сборки с учётом ограничений и уже выбранных комплектующих:
   - GPU (Видеокарта)
   - CPU + Motherboard (Процессор + материнская плата)
   - RAM (ОЗУ)
   - Storage (Накопитель)
   - PSU (блок питания)
   - Case (корпус)
   - Cooler (система охлаждения)
3. На выходе — полная сборка с ценами, характеристиками комплектующих и ссылками на товары

Полная совместимость и сбалансированность комплектующих гарантирована.

---

## Стек

| Компонент | Технология |
|---|---|
| LLM | Llama 4 Scout 17B (HF), Llama 3.3 70B (Groq), Gemini 2.0 Flash (Google) |
| Агентный фреймворк | [smolagents](https://github.com/huggingface/smolagents) — `CodeAgent` |
| База данных | PostgreSQL via [Supabase](https://supabase.com) |
| Клиент БД | `supabase-py`, `psycopg2` |
| Данные о ценах | Wildberries |

---

## База данных (Supabase)

Агент подключается к Supabase через клиент `supabase-py` и вызывает RPC-функцию `run_query` для выполнения SQL-запросов. В базе хранятся:

- Цены и характеристики комплектующих (GPU, CPU, MB, RAM, SSD, PSU, Case, Cooler)
- Бенчмарки и тесты производительности
- Ссылки на товары на Wildberries

Инструмент агента:
```python
@tool
def query_database(sql: str) -> str:
    """Query the PC components database to get prices, benchmarks and compatibility info."""
```

---

## Установка

```bash
pip install smolagents psycopg2-binary python-dotenv requests supabase litellm
```

---

## Конфигурация

Создай файл `.env` в корне проекта:

```env
HF_TOKEN=             # Hugging Face API токен
SUPABASE_DB_URL=      # PostgreSQL connection string от Supabase
GROQ_API_KEY=         # (опционально) Groq API ключ
GOOGLE_API_KEY=       # (опционально) Google AI Studio ключ
```

---

## Запуск

Открой и запусти `agent.ipynb` в Jupyter. Измени запрос в ячейке:

```python
query = "собери ПК за 120тр для киберпанк и кс2"
```

Агент запускается через `agent_init.run(query)`.

---

## Выбор LLM-провайдера

В ноутбуке поддерживаются три провайдера:

```python
model = make_model('hf')      # Llama 4 Scout via HuggingFace Inference API <- по умолчанию
model = make_model('groq')    # Llama 3.3 70B via Groq
model = make_model('google')  # Gemini 2.0 Flash via Google AI Studio
```

---

## Пример результата

```
GPU:     Sapphire AMD Radeon RX 9070 PULSE     — 57 544 ₽
CPU:     AMD Ryzen 5 5600                      — 17 228 ₽ (вместе с MB)
MB:      ASRock B550M-HDV                      ↑
RAM:     Kingston Fury DDR4 3200MHz 16Gb       — 12 700 ₽
Storage: MSI SPATIUM M461 1TB                  — 12 663 ₽
PSU:     Lian Li EDGE 1000W Platinum           —  7 021 ₽
Case:    ZALMAN N4 Rev.1                       —  3 577 ₽
Cooler:  ID-COOLING FROZN A720                 —  4 164 ₽
                                         Итого: ~114 897 ₽
```

Каждый компонент — со ссылкой на Wildberries.

---

## Структура проекта

```
pc-assembler/
├── agent.ipynb        # Основной ноутбук с агентом
├── prompt.py          # Системные промпты для агентов
├── update_prices.py   # Обновление цен (в разработке)
├── .env               # Переменные окружения -> .gitignore
└── README.md
```

---