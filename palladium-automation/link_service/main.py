from fastapi import FastAPI
from link_service.routes import health, links

app = FastAPI(title="Link Service API")

# Include routers
app.include_router(health.router)
app.include_router(links.router)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("link_service.main:app", host="0.0.0.0", port=8000, reload=True)