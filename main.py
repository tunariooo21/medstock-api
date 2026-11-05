from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from admin_panel import admin_qur
from auth import router as auth_router
from routes_manager import router as manager_router
from routes_prices import router as prices_router
from routes_reference import router as reference_router
from routes_reports import router as reports_router
from routes_stock import router as stock_router
from routes_summary import router as summary_router

app = FastAPI(title="MedStock API")

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"(http://(localhost|127\.0\.0\.1)(:\d+)?|https://[a-z0-9-]+\.netlify\.app)",
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(summary_router)
app.include_router(stock_router)
admin_qur(app)
app.include_router(reference_router)
app.include_router(reports_router)
app.include_router(manager_router)
app.include_router(prices_router)


@app.get("/")
def kok():
    return {"mesaj": "MedStock API işləyir"}