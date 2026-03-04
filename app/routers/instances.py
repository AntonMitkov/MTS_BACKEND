from fastapi import APIRouter, HTTPException, status, Query
from core.lxd import client
from schemas.models import InstanceCreate

router = APIRouter(prefix="/instances", tags=["Instances"])

@router.post("", status_code=status.HTTP_201_CREATED)
def create_instance(data: InstanceCreate):
    if client.instances.exists(data.name):
        raise HTTPException(status_code=400, detail="Инстанс уже существует")
    
    # Проверяем, существует ли запрошенная сеть
    if not client.networks.exists(data.network_name):
        raise HTTPException(status_code=404, detail=f"Сеть {data.network_name} не найдена")

    # Формируем конфиг. Явно задаем root диск и сетевой интерфейс eth0
    config = {
        "name": data.name,
        "source": {
            "type": "image",
            "alias": data.image  # Ожидаем, что образ есть локально (как твой ubuntu/22.04)
        },
        "profiles": data.profiles,
        "type": data.type,
        "config": data.config,
        "devices": {
            # Явное указание диска спасает от ошибки "No root device"
            "root": {
                "path": "/",
                "pool": data.storage_pool,
                "type": "disk"
            },
            # Явное подключение к выбранной сети
            "eth0": {
                "name": "eth0",
                "network": data.network_name,
                "type": "nic"
            }
        }
    }
    
    try:
        instance = client.instances.create(config, wait=True)
        instance.start(wait=True)
        
        # Пытаемся получить IP адрес (может занять пару секунд после старта)
        state = instance.state()
        ip_address = "IP выдается..."
        if state.network and 'eth0' in state.network:
            addresses = state.network['eth0'].get('addresses', [])
            for addr in addresses:
                if addr['family'] == 'inet': # Берем IPv4
                    ip_address = addr['address']
                    break

        return {
            "status": "created and started", 
            "name": instance.name,
            "network": data.network_name,
            "ip_address": ip_address
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"LXD Error: {str(e)}")

@router.get("")
def list_instances():
    instances = client.instances.all()
    return [{"name": i.name, "status": i.status} for i in instances]

@router.delete("/{name}")
def delete_instance(name: str):
    if not client.instances.exists(name):
        raise HTTPException(status_code=404, detail="Инстанс не найден")
    
    instance = client.instances.get(name)
    if instance.status == "Running":
        instance.stop(wait=True) # Форсированно останавливаем перед удалением
        
    instance.delete(wait=True)
    return {"detail": "Инстанс успешно удален"}

@router.get("/{name}")
def get_instance_details(name: str):
    if not client.instances.exists(name):
        raise HTTPException(status_code=404, detail="Инстанс не найден")
    
    instance = client.instances.get(name)
    state = instance.state()
    
    return {
        "name": instance.name,
        "status": instance.status,
        "location": instance.location,
        "type": instance.type,
        "architecture": instance.architecture,
        "created_at": instance.created_at,
        "config": instance.config,
        "state": {
            "status": state.status,
            "cpus": state.cpu,
            "memory": state.memory,
            "network": state.network
        }
    }

@router.post("/{name}/action")
def manage_instance_status(name: str, action: str = Query(..., regex="^(start|stop|restart)$")):
    """
    Изменение статуса: start, stop или restart
    """
    if not client.instances.exists(name):
        raise HTTPException(status_code=404, detail="Инстанс не найден")
    
    instance = client.instances.get(name)
    
    try:
        if action == "start":
            if instance.status == "Running":
                return {"message": "Инстанс уже запущен"}
            instance.start(wait=True)
        elif action == "stop":
            if instance.status == "Stopped":
                return {"message": "Инстанс уже остановлен"}
            instance.stop(wait=True)
        elif action == "restart":
            instance.restart(wait=True)
            
        return {"status": "success", "action": action, "current_status": instance.status}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка при выполнении {action}: {str(e)}")

@router.delete("/{name}")
def delete_instance(name: str):
    if not client.instances.exists(name):
        raise HTTPException(status_code=404, detail="Инстанс не найден")
    
    instance = client.instances.get(name)
    try:
        if instance.status == "Running":
            instance.stop(wait=True)
        instance.delete(wait=True)
        return {"detail": f"Инстанс {name} успешно удален"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка при удалении: {str(e)}")