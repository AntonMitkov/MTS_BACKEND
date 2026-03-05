from fastapi import FastAPI
from .routers import instances, network, snapshots, resources, infrastructure

app = FastAPI(title="Hackathon IAAS API")

app.include_router(instances.router)
app.include_router(infrastructure.router)
app.include_router(network.router)
app.include_router(snapshots.router)
app.include_router(resources.router)

@app.get("/")
def root():
    return {"message": "API is running. Go to /docs for Swagger UI"}
