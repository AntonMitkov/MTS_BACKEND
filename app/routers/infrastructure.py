from fastapi import APIRouter, HTTPException, status, Query
from ..schemas.models import TerraformDeploy
from typing import List, Optional, Dict
from ..services.terraform_service import TerraformService
import re
import httpx

def api_response(status="success", message="", data=None, metadata=None):
    return {
        "status": status,
        "message": message,
        "data": data,
        "metadata": metadata or {}
    }

def clean_tf_output(text):
    """Очищает вывод Terraform от цветовых кодов и мусора"""
    return re.sub(r'\x1b\[[0-9;]*m', '', str(text)).strip()

router = APIRouter(prefix="/infrastructure", tags=["Terraform Orchestration"])
tf_service = TerraformService()

@router.post("/deploy", status_code=status.HTTP_201_CREATED)
def deploy_stack(data: TerraformDeploy):
    try:
        raw_output = tf_service.deploy(data.project_name, data.network_name, data.instances)
        
        # Простая очистка вывода от мусора и ANSI-кодов (цветов)
        clean_output = re.sub(r'\x1b\[[0-9;]*m', '', raw_output)
        
        # Ищем финальную строку статистики
        summary = "Deployment completed"
        if "Apply complete!" in clean_output:
            summary = clean_output.split("Apply complete!")[-1].strip()

        return {
            "status": "success",
            "project": data.project_name,
            "message": "Инфраструктура успешно развернута",
            "summary": summary,
            "instances_created": [inst.name for inst in data.instances],
            "network": data.network_name
        }
    except Exception as e:
        # Если ошибка, возвращаем её красиво
        error_msg = re.sub(r'\x1b\[[0-9;]*m', '', str(e))
        raise HTTPException(status_code=500, detail={
            "status": "error",
            "message": "Ошибка при развертывании Terraform",
            "details": error_msg
        })

@router.post("/deploy-tf-link")
async def deploy_from_tf_link(
    project_name: str = Query(..., example="custom-hcl-project"),
    url: str = Query(..., description="Ссылка на сырой .tf файл (например, GitHub Raw)")
):
    """
    Infrastructure as a Link: принимает ссылку на файл .tf
    """
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url)
            if response.status_code != 200:
                raise HTTPException(status_code=400, detail="Не удалось скачать .tf файл")
            
            raw_output = tf_service.deploy_raw_hcl(project_name, response.text)
            
            # Чистим лог и ищем итог
            clean_log = clean_tf_output(raw_output)
            summary = "No changes"
            if "Apply complete!" in clean_log:
                summary = clean_log.split("Apply complete!")[-1].strip()

            return api_response(
                message="Инфраструктура успешно развернута",
                data={
                    "project": project_name,
                    "summary": summary,
                    "log_preview": clean_log[-300:] # последние 300 символов лога
                }
            )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/projects")
def get_all_projects():
    """Список всех активных IaC проектов"""
    return {
        "status": "success",
        "projects": tf_service.list_projects()
    }

@router.get("/inventory")
def get_infrastructure_inventory():
    """
    Показывает "карту" инфраструктуры: какие машины привязаны к каким IaC проектам.
    """
    try:
        inventory = tf_service.get_projects_inventory()
        
        # Разделяем: кто в проектах, а кто "одиночка"
        # Для этого получим список вообще всех имен из LXD
        from ..core.lxd import client
        all_lxd_names = [i.name for i in client.instances.all()]
        
        # Собираем все имена, которые числятся за проектами
        names_in_projects = []
        for item in inventory:
            names_in_projects.extend(item["instances"])
            
        # Находим тех, кто создан вручную (нет ни в одном проекте)
        standalone_instances = [name for name in all_lxd_names if name not in names_in_projects]

        return api_response(
            message="Инвентаризация инфраструктуры завершена",
            data={
                "projects": inventory,
                "standalone": standalone_instances
            },
            metadata={
                "total_projects": len(inventory),
                "total_instances": len(all_lxd_names)
            }
        )
    except Exception as e:
        return api_response(status="error", message=str(e))

@router.delete("/{project_name}")
def delete_project(project_name: str):
    """Удаление всего проекта (всех машин и сетей в нем)"""
    try:
        tf_service.destroy(project_name)
        return {
            "status": "success",
            "message": f"Проект {project_name} и все его ресурсы полностью удалены"
        }
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Проект не найден")
    except Exception as e:
        error_msg = re.sub(r'\x1b\[[0-9;]*m', '', str(e))
        raise HTTPException(status_code=500, detail=error_msg)


@router.post("/generate-link")
async def generate_infrastructure_link(data: TerraformDeploy):
    """
    Генерирует .tf файл на основе JSON, сохраняет в Supabase и дает ссылку.
    """
    try:
        # Загружаем в Supabase и получаем ссылку
        cloud_url, raw_hcl = tf_service.save_and_upload_hcl(
            data.network_name, 
            data.instances, 
            data.project_name
        )
        
        return {
            "status": "success",
            "project_name": data.project_name,
            "shareable_url": cloud_url,
            "instruction": "Отправьте этот URL в эндпоинт /deploy-tf-link для развертывания",
            "preview_hcl": raw_hcl[:200] + "..." # Показываем кусочек кода для проверки
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/export-to-link")
async def export_existing_infrastructure(
    project_name: str = Query(..., example="my-manual-stack"),
    instance_names: List[str] = Query(..., description="Список имен существующих ВМ для экспорта")
):
    """
    Берет уже созданные вручную машины и генерирует для них Terraform-ссылку.
    """
    try:
        cloud_url, raw_hcl = tf_service.export_project_to_supabase(
            project_name, 
            instance_names
        )
        
        return {
            "status": "success",
            "message": "Существующая архитектура экспортирована в Terraform файл",
            "project": project_name,
            "supabase_url": cloud_url,
            "exported_resources": instance_names
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
