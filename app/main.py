from fastapi import FastAPI
from routers import instances, network

app = FastAPI(title="Hackathon IAAS API")

app.include_router(instances.router)
app.include_router(network.router)

@app.get("/")
def root():
    return {"message": "API is running. Go to /docs for Swagger UI"}