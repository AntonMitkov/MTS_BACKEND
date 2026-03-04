from pydantic import BaseModel, Field
from typing import Optional, Dict, List

# --- Схемы для сетей ---
class NetworkConfig(BaseModel):
    ipv4_address: str = Field(default="10.0.20.1/24")
    ipv4_nat: str = Field(default="true")
    ipv6_address: str = Field(default="none")

class NetworkCreate(BaseModel):
    name: str = Field(..., example="my-custom-net")
    description: Optional[str] = "IAAS Custom Network"
    config: Optional[NetworkConfig] = NetworkConfig()

# --- Схемы для инстансов ---
class InstanceCreate(BaseModel):
    name: str = Field(..., example="web-server-01")
    image: str = Field(default="ubuntu/22.04", description="Алиас локального образа")
    type: str = Field(default="container")
    profiles: List[str] = ["default"]
    network_name: str = Field(default="lxdbr0", description="Имя сети для подключения")
    storage_pool: str = Field(default="default", description="Имя пула хранилища (обычно default)")
    config: Optional[Dict[str, str]] = {"limits.cpu": "1", "limits.memory": "512MB"}