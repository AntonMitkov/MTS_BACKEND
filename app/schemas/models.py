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

class InstanceCreate(BaseModel):
    name: str = Field(..., example="web-server-01")
    image: str = Field(default="ubuntu/22.04")
    type: str = Field(default="container")
    profiles: List[str] = ["default"]
    network_name: str = Field(default="lxdbr0")
    storage_pool: str = Field(default="default")
    config: Optional[Dict[str, str]] = {"limits.cpu": "1", "limits.memory": "512MB"}
    disk: Optional[str] = Field(default="10GB", description="Размер диска, например 10GB") # НОВОЕ ПОЛЕ
    ssh_password: Optional[str] = "hackathon2024"
    ssh_key: Optional[str] = None

class SnapshotCreate(BaseModel):
    instance_name: str = Field(..., example="web-server-01")
    snapshot_name: str = Field(..., example="backup-before-update")
    stateful: bool = Field(default=False)

class SnapshotRestore(BaseModel):
    instance_name: str = Field(..., example="web-server-01")
    snapshot_name: str = Field(..., example="backup-before-update")

class UpdateResources(BaseModel):
    cpus: Optional[str] = Field(None, example="2")
    memory: Optional[str] = Field(None, example="1GB")
    disk: Optional[str] = Field(None, example="20GB", description="Размер диска (например, 10GB, 50GB)")

class TerraformInstance(BaseModel):
    name: str
    image: str = "ubuntu:22.04"
    cpu: str = "1"
    memory: str = "512MB"

class TerraformDeploy(BaseModel):
    project_name: str = Field(..., example="my-web-stack")
    network_name: str = Field(default="lxd-tf-net")
    instances: List[TerraformInstance]