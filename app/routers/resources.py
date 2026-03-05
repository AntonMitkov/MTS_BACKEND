from fastapi import APIRouter, HTTPException, status
from ..core.lxd import client
from ..schemas.models import UpdateResources
import time

router = APIRouter(prefix="/resources", tags=["Resources & Monitoring"])


@router.patch("/{instance_name}")
def update_instance_resources(instance_name: str, data: UpdateResources):
    if not client.instances.exists(instance_name):
        raise HTTPException(status_code=404, detail="Инстанс не найден")
    
    instance = client.instances.get(instance_name)
    
    # 1. Сначала обновляем CPU и RAM (они в config)
    new_config = {}
    if data.cpus:
        new_config["limits.cpu"] = data.cpus
    if data.memory:
        new_config["limits.memory"] = data.memory
    
    if new_config:
        instance.config.update(new_config)

    # 2. Обновляем ДИСК (он в devices)
    if data.disk:
        # У LXD устройства хранятся в словаре devices. 
        # Обычно корневой диск называется 'root'.
        devices = instance.devices.copy() # Копируем текущие устройства
        
        if 'root' in devices:
            # Обновляем или добавляем параметр size
            devices['root']['size'] = data.disk
        else:
            # Если вдруг устройства root нет (такое бывает в кривых профилях),
            # мы его создаем, но это редкий случай.
            devices['root'] = {
                "path": "/",
                "pool": "default", # предполагаем, что пул называется default
                "type": "disk",
                "size": data.disk
            }
        
        instance.devices = devices # Присваиваем обновленный словарь обратно

    try:
        # Сохраняем все изменения одним махом
        instance.save(wait=True)
        
        return {
            "status": "updated",
            "instance": instance_name,
            "applied_resources": {
                "cpus": data.cpus,
                "memory": data.memory,
                "disk": data.disk
            }
        }
    except Exception as e:
        raise HTTPException(
            status_code=500, 
            detail=f"LXD Error: {str(e)}. Note: Shrinking disk is often not supported while running."
        )

        
def calculate_cpu_percentage(instance, interval=0.5):
    """
    Замеряет использование CPU за короткий интервал и вычисляет % нагрузки.
    """
    # Первый замер
    st1 = instance.state()
    cpu_start = st1.cpu['usage']
    time_start = time.time()
    
    time.sleep(interval) # Короткая пауза для замера
    
    # Второй замер
    st2 = instance.state()
    cpu_end = st2.cpu['usage']
    time_end = time.time()
    
    # Вычисляем разницу в наносекундах
    cpu_delta = cpu_end - cpu_start
    time_delta = (time_end - time_start) * 1_000_000_000 # переводим в наносекунды
    
    # Получаем количество ядер (по умолчанию 1, если не задано)
    cpus_count = int(instance.config.get("limits.cpu", 1))
    
    # Формула: (дельта использования CPU) / (дельта времени * кол-во ядер) * 100
    cpu_percent = (cpu_delta / (time_delta * cpus_count)) * 100
    return round(min(cpu_percent, 100.0), 2) # Ограничиваем 100%


@router.get("/{instance_name}/metrics")
def get_detailed_metrics(instance_name: str):
    """
    Получение расширенных метрик: CPU %, RAM %, Disk %
    """
    if not client.instances.exists(instance_name):
        raise HTTPException(status_code=404, detail="Инстанс не найден")
    
    instance = client.instances.get(instance_name)
    state = instance.state()
    
    # 1. CPU Загрузка
    cpu_load = calculate_cpu_percentage(instance)
    
    # 2. RAM Метрики
    mem_used = state.memory['usage']
    mem_limit_raw = instance.config.get("limits.memory", "512MB")
    # Простой парсинг лимита для расчета % (переводим в байты)
    if "GB" in mem_limit_raw:
        mem_limit_bytes = int(mem_limit_raw.replace("GB", "")) * 1024 * 1024 * 1024
    else:
        mem_limit_bytes = int(mem_limit_raw.replace("MB", "")) * 1024 * 1024
    
    mem_percent = round((mem_used / mem_limit_bytes) * 100, 2)

    # 3. Диск Метрики
    disk_used = 0
    disk_total = 0
    disk_percent = 0
    
    if state.disk and 'root' in state.disk:
        disk_used = state.disk['root'].get('usage', 0)
        # Пытаемся достать лимит диска
        disk_limit_raw = instance.devices.get("root", {}).get("size", "10GB")
        disk_total = int(disk_limit_raw.replace("GB", "")) * 1024 * 1024 * 1024
        disk_percent = round((disk_used / disk_total) * 100, 2)

    return {
        "status": "success",
        "instance": instance_name,
        "metrics": {
            "cpu": {
                "load_percent": cpu_load,
                "cores_allocated": instance.config.get("limits.cpu", 1)
            },
            "memory": {
                "used_mb": round(mem_used / 1024 / 1024, 2),
                "limit_mb": round(mem_limit_bytes / 1024 / 1024, 2),
                "usage_percent": mem_percent
            },
            "disk": {
                "used_gb": round(disk_used / 1024 / 1024 / 1024, 2),
                "total_gb": round(disk_total / 1024 / 1024 / 1024, 2),
                "usage_percent": disk_percent
            }
        },
        "processes_count": state.processes
    }