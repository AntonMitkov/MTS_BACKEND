from fastapi import APIRouter, HTTPException, status, Query
from ..core.lxd import client
from ..schemas.models import InstanceCreate
import random

router = APIRouter(prefix="/instances", tags=["Instances"])

from fastapi import APIRouter, HTTPException, status, Query
from ..core.lxd import client
from ..schemas.models import InstanceCreate
import random

router = APIRouter(prefix="/instances", tags=["Instances"])

def extract_ssh_port(instance):
    """Находит порт SSH-прокси в устройствах"""
    devices = instance.devices
    if "ssh-proxy" in devices:
        listen_str = devices["ssh-proxy"].get("listen", "")
        parts = listen_str.split(":")
        if len(parts) >= 3:
            return parts[-1]
    return None

def extract_network_name(instance):
    """ Находит имя сети (bridge), к которой подключен инстанс """
    for dev_name, dev_cfg in instance.devices.items():
        if dev_cfg.get("type") == "nic":
            # Возвращаем имя сети, указанное в параметре 'network'
            return dev_cfg.get("network", "unknown")
    return "none"

def get_instance_resources_info(instance):
    """Собирает данные о лимитах и текущем потреблении"""
    state = instance.state()
    allocated = {
        "cpu_cores": instance.config.get("limits.cpu", "unlimited"),
        "memory": instance.config.get("limits.memory", "unlimited"),
        "disk": instance.devices.get("root", {}).get("size", "unlimited")
    }
    mem_used_bytes = state.memory.get("usage", 0)
    disk_used_bytes = 0
    if state.disk and 'root' in state.disk:
        disk_used_bytes = state.disk['root'].get('usage', 0)

    return {
        "allocated": allocated,
        "usage": {
            "cpu_nanoseconds": state.cpu.get("usage", 0),
            "memory_human": f"{round(mem_used_bytes / 1024 / 1024, 2)} MB",
            "disk_human": f"{round(disk_used_bytes / 1024 / 1024 / 1024, 2)} GB"
        }
    }

@router.get("")
def list_instances():
    """Список всех ВМ с информацией о сети и лимитах"""
    instances = client.instances.all()
    result = []
    for i in instances:
        result.append({
            "name": i.name,
            "status": i.status,
            "network": extract_network_name(i), # <-- ДОБАВЛЕНО
            "ssh_port": extract_ssh_port(i),
            "memory_limit": i.config.get("limits.memory", "unlimited"),
            "cpu_limit": i.config.get("limits.cpu", "unlimited")
        })
    return result


@router.get("/{name}")
def get_instance_details(name: str):
    if not client.instances.exists(name):
        raise HTTPException(status_code=404, detail="Инстанс не найден")
    
    instance = client.instances.get(name)
    state = instance.state()
    ssh_port = extract_ssh_port(instance)
    
    # Красивый расчет ресурсов
    mem_limit = instance.config.get("limits.memory", "N/A")
    mem_used = f"{round(state.memory['usage'] / 1024 / 1024, 2)} MB"
    
    return {
        "status": "success",
        "data": {
            "name": instance.name,
            "state": instance.status,
            "network": {
                "bridge": extract_network_name(instance),
                "ips": [addr['address'] for net in state.network.values() 
                        for addr in net['addresses'] if addr['family'] == 'inet']
            },
            "access": {
                "ssh_port": ssh_port,
                "ssh_command": f"ssh ubuntu@95.169.204.226 -p {ssh_port}" if ssh_port else "N/A"
            }
        }
    }


# --- Методы POST, DELETE, ACTION остаются без изменений (см. предыдущие сообщения) ---
@router.post("", status_code=status.HTTP_201_CREATED)
def create_instance(data: InstanceCreate):
    if client.instances.exists(data.name):
        raise HTTPException(status_code=400, detail="Инстанс уже существует")

    external_ssh_port = random.randint(2000, 9000)
    user_data = f"""#cloud-config
ssh_pwauth: yes
users:
  - name: ubuntu
    sudo: ALL=(ALL) NOPASSWD:ALL
    shell: /bin/bash
    lock_passwd: false
    passwd: {data.ssh_password}
"""
    if data.ssh_key:
        user_data += f"\n    ssh_authorized_keys:\n      - {data.ssh_key}"

    root_device = {"path": "/", "pool": data.storage_pool, "type": "disk"}
    if data.disk:
        root_device["size"] = data.disk

    config = {
        "name": data.name,
        "source": {"type": "image", "alias": data.image},
        "profiles": data.profiles,
        "config": {**data.config, "user.user-data": user_data},
        "devices": {
            "root": root_device,
            "eth0": {"name": "eth0", "network": data.network_name, "type": "nic"},
            "ssh-proxy": {
                "type": "proxy",
                "listen": f"tcp:0.0.0.0:{external_ssh_port}",
                "connect": "tcp:127.0.0.1:22"
            }
        }
    }

    try:
        instance = client.instances.create(config, wait=True)
        instance.start(wait=True)
        return {
            "status": "created",
            "name": instance.name,
            "ssh_port": external_ssh_port,
            "disk_size": data.disk,
            "ssh_command": f"ssh ubuntu@95.169.204.226 -p {external_ssh_port}",
            "password": data.ssh_password
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/{name}/action")
def manage_instance_status(name: str, action: str = Query(..., regex="^(start|stop|restart)$")):
    if not client.instances.exists(name):
        raise HTTPException(status_code=404, detail="Инстанс не найден")
    instance = client.instances.get(name)
    try:
        if action == "start": instance.start(wait=True)
        elif action == "stop": instance.stop(wait=True)
        elif action == "restart": instance.restart(wait=True)
        return {"status": "success", "action": action, "current_status": instance.status}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/{name}")
def delete_instance(name: str):
    if not client.instances.exists(name):
        raise HTTPException(status_code=404, detail="Инстанс не найден")
    instance = client.instances.get(name)
    try:
        if instance.status == "Running": instance.stop(wait=True)
        instance.delete(wait=True)
        return {"detail": f"Инстанс {name} успешно удален"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))