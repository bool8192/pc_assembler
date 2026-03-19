# PC Assembler Agent

AI-агент для подбора комплектующих ПК по бюджету и целевой производительности.

## Stack

- Llama 4 Scout (HF Inference API)
- smolagents
- PostgreSQL (Supabase)
- psycopg2

## Setup

```bash
pip install smolagents psycopg2-binary python-dotenv requests
```

Создай `.env`:

```
HF_TOKEN=
SUPABASE_DB_URL=
WB_API_KEY=
```

## Usage

```bash
# Запуск агента
python agent.py

# Обновление цен с Wildberries
python update_prices.py
```

## Project Structure

```
pc-assembler/
├── agent.py
├── update_prices.py
├── .env
└── README.md
```