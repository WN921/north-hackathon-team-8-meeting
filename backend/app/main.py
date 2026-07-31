from fastapi import FastAPI

app = FastAPI(
    title="Meeting Room Booking API",
    description="本地会务系统 FastAPI 后端 API。RFC-0002 定义完整 API 契约。",
    version="0.1.0",
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
