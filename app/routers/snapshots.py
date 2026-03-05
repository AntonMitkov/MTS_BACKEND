from fastapi import status
from ..core.lxd import client
from ..schemas.models import SnapshotCreate, SnapshotRestore
import os
import uuid
from fastapi import APIRouter, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
from fastapi.responses import StreamingResponse

router = APIRouter(prefix="/snapshots", tags=["Snapshots"])

@router.post("", status_code=status.HTTP_201_CREATED)
def create_snapshot(data: SnapshotCreate):
    if not client.instances.exists(data.instance_name):
        raise HTTPException(status_code=404, detail=f"Инстанс {data.instance_name} не найден")
    
    instance = client.instances.get(data.instance_name)
    
    # ИСПРАВЛЕНИЕ: Проверяем существование через список имен
    all_snap_names = [s.name for s in instance.snapshots.all()]
    if data.snapshot_name in all_snap_names:
        raise HTTPException(status_code=400, detail="Снэпшот с таким именем уже существует")
    
    try:
        instance.snapshots.create(data.snapshot_name, stateful=data.stateful, wait=True)
        return {"message": "Снэпшот успешно создан", "snapshot": data.snapshot_name}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

import time # Добавь импорт в начало файла

@router.post("/restore")
def restore_from_snapshot(data: SnapshotRestore):
    if not client.instances.exists(data.instance_name):
        raise HTTPException(status_code=404, detail="Инстанс не найден")
    
    # 1. Получаем свежий объект инстанса
    instance = client.instances.get(data.instance_name)

    # Проверяем наличие снэпшота
    all_snap_names = [s.name for s in instance.snapshots.all()]
    if data.snapshot_name not in all_snap_names:
        raise HTTPException(status_code=404, detail="Снэпшот не найден")

    try:
        # 2. Принудительно останавливаем, если он запущен
        if instance.status == "Running":
            instance.stop(wait=True)
        
        # 3. Находим снэпшот и восстанавливаем
        snapshot = instance.snapshots.get(data.snapshot_name)
        snapshot.restore(wait=True)
        
        # --- КРИТИЧЕСКИ ВАЖНЫЙ МОМЕНТ ---
        # Даем LXD 2 секунды "прийти в себя" и заново получаем объект из базы
        time.sleep(2)
        instance = client.instances.get(data.instance_name) 
        
        # 4. Проверяем статус и запускаем
        if instance.status != "Running":
            instance.start(wait=True)
            
        return {
            "message": f"Инстанс {data.instance_name} восстановлен и запущен",
            "current_status": instance.status
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка при восстановлении: {str(e)}")

@router.delete("/{instance_name}/{snapshot_name}")
def delete_snapshot(instance_name: str, snapshot_name: str):
    if not client.instances.exists(instance_name):
        raise HTTPException(status_code=404, detail="Инстанс не найден")
    
    instance = client.instances.get(instance_name)
    
    # ИСПРАВЛЕНИЕ: Проверка существования
    all_snap_names = [s.name for s in instance.snapshots.all()]
    if snapshot_name not in all_snap_names:
        raise HTTPException(status_code=404, detail="Снэпшот не найден")
    
    try:
        # Получаем объект снэпшота и удаляем его
        snap = instance.snapshots.get(snapshot_name)
        snap.delete(wait=True)
        return {"message": f"Снэпшот {snapshot_name} удален"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{instance_name}")
def list_instance_snapshots(instance_name: str):
    if not client.instances.exists(instance_name):
        raise HTTPException(status_code=404, detail="Инстанс не найден")
    
    instance = client.instances.get(instance_name)
    return [
        {"name": s.name, "created_at": s.created_at, "stateful": s.stateful} 
        for s in instance.snapshots.all()
    ]

@router.get("/{instance_name}/{snapshot_name}/download")
def download_snapshot(instance_name: str, snapshot_name: str):
    if not client.instances.exists(instance_name):
        raise HTTPException(status_code=404, detail="Инстанс не найден")
    
    instance = client.instances.get(instance_name)
    
    try:
        # 1. Публикуем (это всё равно займет 5-15 секунд, это неизбежно)
        snapshot = instance.snapshots.get(snapshot_name)
        image = snapshot.publish(wait=True)
        
        # 2. Создаем генератор, который будет читать данные из LXD и сразу отдавать в сеть
        def image_streamer():
            try:
                for chunk in image.export():
                    yield chunk
                # После того как всё отдано, удаляем временный образ
                image.delete(wait=True)
            except Exception as e:
                print(f"Ошибка при стриминге: {e}")

        # 3. Отдаем как стрим
        return StreamingResponse(
            image_streamer(),
            media_type='application/octet-stream',
            headers={
                "Content-Disposition": f"attachment; filename={instance_name}_{snapshot_name}.tar.gz"
            }
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка: {str(e)}")