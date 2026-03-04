from fastapi import APIRouter, HTTPException, status
from core.lxd import client
from schemas.models import NetworkCreate

router = APIRouter(prefix="/networks", tags=["Networks"])

@router.post("", status_code=status.HTTP_201_CREATED)
def create_network(nw_data: NetworkCreate):
    if client.networks.exists(nw_data.name):
        raise HTTPException(status_code=400, detail="Сеть уже существует")
    
    config_dict = {
        "ipv4.address": nw_data.config.ipv4_address,
        "ipv4.nat": nw_data.config.ipv4_nat,
        "ipv6.address": nw_data.config.ipv6_address
    }
    
    try:
        network = client.networks.create(
            nw_data.name, 
            description=nw_data.description, 
            type='bridge', 
            config=config_dict
        )
        return {"status": "created", "name": network.name}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка создания сети: {str(e)}")

@router.get("")
def list_networks():
    networks = client.networks.all()
    return [{"name": n.name, "managed": n.managed, "type": n.type} for n in networks]

@router.delete("/{name}")
def delete_network(name: str):
    if not client.networks.exists(name):
        raise HTTPException(status_code=404, detail="Сеть не найдена")
    
    try:
        network = client.networks.get(name)
        # Проверка: используется ли сеть кем-то (опционально, LXD сам выдаст ошибку)
        if network.used_by:
             raise HTTPException(
                 status_code=400, 
                 detail=f"Нельзя удалить сеть, она используется: {network.used_by}"
             )
        
        network.delete()
        return {"detail": f"Сеть {name} успешно удалена"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка при удалении сети: {str(e)}")