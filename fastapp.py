import json
import uuid
from collections.abc import Generator

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel


app = FastAPI()

class Request(BaseModel):
    query: str

@app.post("/start")
def start(req: Request):
    """
    Принимает запрос, создаёт job_id, сохраняет генератор.
    Возвращает job_id — браузер использует его для подписки на стрим.
    """

    return {"job_id": job_id}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)