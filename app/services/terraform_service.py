import os
import subprocess
import shutil
import random
import uuid  # Нужно для генерации имен файлов для Supabase
from pathlib import Path
from ..core.lxd import client        # КРИТИЧНО: доступ к LXD
from ..core.supabase_client import supabase

class TerraformService:
    BASE_DIR = Path("./terraform_deployments")

    def __init__(self):
        # Создаем базовую директорию при инициализации
        self.BASE_DIR.mkdir(exist_ok=True, parents=True)

    def list_projects(self):
        """
        Именно этого метода не хватало! 
        Возвращает список имен папок (проектов).
        """
        if not self.BASE_DIR.exists():
            return []
        # Берем только директории внутри BASE_DIR
        return [d.name for d in self.BASE_DIR.iterdir() if d.is_dir()]

    def _generate_hcl(self, network_name: str, instances: list) -> str:
        """Генерация конфигурации Terraform (HCL)"""
        hcl = f"""
terraform {{
  required_providers {{
    lxd = {{
      source = "terraform-lxd/lxd"
      version = ">= 2.0.0"
    }}
  }}
}}

provider "lxd" {{
  generate_client_certificates = false
  accept_remote_certificate    = true
}}

resource "lxd_network" "{network_name}" {{
  name = "{network_name}"
  config = {{
    "ipv4.address" = "10.0.99.1/24"
    "ipv4.nat"     = "true"
    "ipv6.address" = "none"
  }}
}}
"""
        for inst in instances:
            ssh_port = random.randint(10000, 15000)
            hcl += f"""
resource "lxd_instance" "{inst.name}" {{
  name      = "{inst.name}"
  image     = "{inst.image}"
  type      = "container"
  wait_for_network = false

  limits = {{
    cpu    = "{inst.cpu}"
    memory = "{inst.memory}"
  }}

  device {{
    name = "eth0"
    type = "nic"
    properties = {{
      network = lxd_network.{network_name}.name
    }}
  }}

  device {{
    name = "ssh-proxy"
    type = "proxy"
    properties = {{
      listen  = "tcp:0.0.0.0:{ssh_port}"
      connect = "tcp:127.0.0.1:22"
    }}
  }}
}}
"""
        return hcl

    def get_projects_inventory(self):
        """
        Сканирует файлы состояния (.tfstate) и возвращает 
        сопоставление: Проект -> Список инстансов
        """
        inventory = []
        
        if not self.BASE_DIR.exists():
            return []

        for project_dir in self.BASE_DIR.iterdir():
            if not project_dir.is_dir():
                continue
            
            state_file = project_dir / "terraform.tfstate"
            project_instances = []
            
            if state_file.exists():
                try:
                    with open(state_file, 'r') as f:
                        state_data = json.load(f)
                        
                    # Парсим структуру tfstate (ищем ресурсы типа lxd_instance)
                    for resource in state_data.get('resources', []):
                        if resource.get('type') == 'lxd_instance':
                            for instance in resource.get('instances', []):
                                name = instance.get('attributes', {}).get('name')
                                if name:
                                    project_instances.append(name)
                except Exception as e:
                    print(f"Ошибка чтения стейта для {project_dir.name}: {e}")

            inventory.append({
                "project_name": project_dir.name,
                "instances": project_instances,
                "count": len(project_instances)
            })
            
        return inventory

    def run_command(self, command: list, cwd: Path):
        """Запуск команд Terraform и сбор вывода"""
        result = subprocess.run(
            command, cwd=cwd, capture_output=True, text=True
        )
        full_output = f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        
        if result.returncode != 0:
            raise Exception(full_output)
        return full_output

    def deploy(self, project_name: str, network_name: str, instances: list):
        """Развертывание стека"""
        project_path = self.BASE_DIR / project_name
        project_path.mkdir(exist_ok=True)

        with open(project_path / "main.tf", "w") as f:
            f.write(self._generate_hcl(network_name, instances))

        # Последовательно выполняем init и apply
        self.run_command(["terraform", "init"], cwd=project_path)
        output = self.run_command(["terraform", "apply", "-auto-approve"], cwd=project_path)
        return output

    def destroy(self, project_name: str):
        """Удаление ресурсов и папки проекта"""
        project_path = self.BASE_DIR / project_name
        if not project_path.exists():
            raise FileNotFoundError(f"Проект {project_name} не найден")

        self.run_command(["terraform", "destroy", "-auto-approve"], cwd=project_path)
        shutil.rmtree(project_path)
        return f"Проект {project_name} удален"
    
    def save_and_upload_hcl(self, network_name: str, instances: list, project_name: str):
        """Генерирует HCL и загружает его в Supabase Storage"""
        
        # 1. Генерируем текст конфига (используем твой существующий метод)
        hcl_content = self._generate_hcl(network_name, instances)
        
        # 2. Генерируем уникальное имя файла
        file_name = f"{project_name}_{uuid.uuid4().hex[:8]}.tf"
        
        # 3. Загружаем в Supabase Storage
        # Превращаем строку в байты для загрузки
        file_bytes = hcl_content.encode('utf-8')
        
        storage_path = f"configs/{file_name}"
        
        try:
            res = supabase.storage.from_("terraform-files").upload(
                path=storage_path,
                file=file_bytes,
                file_options={"content-type": "text/plain"}
            )
            
            # 4. Получаем публичную ссылку
            public_url = supabase.storage.from_("terraform-files").get_public_url(storage_path)
            return public_url, hcl_content
        except Exception as e:
            raise Exception(f"Supabase upload error: {str(e)}")

    def export_project_to_supabase(self, project_name: str, instance_names: list):
        """
        Читает реальные данные из LXD и создает .tf файл в Supabase
        """
        exported_instances = []
        target_network = "lxdbr0" # По умолчанию

        for name in instance_names:
            if not client.instances.exists(name):
                continue
            
            inst = client.instances.get(name)
            
            # Извлекаем данные для Terraform
            config = {
                "name": inst.name,
                "image": inst.config.get("image.os", "ubuntu") + ":" + inst.config.get("image.version", "22.04"),
                "cpu": inst.config.get("limits.cpu", "1"),
                "memory": inst.config.get("limits.memory", "512MB")
            }
            
            # Пытаемся определить сеть из устройства eth0
            if "eth0" in inst.devices:
                target_network = inst.devices["eth0"].get("network", target_network)
            
            exported_instances.append(config)

        if not exported_instances:
            raise Exception("Не найдены инстансы для экспорта")

        # 1. Генерируем HCL на основе реальных данных
        # Используем вспомогательный класс (обертка над данными)
        from collections import namedtuple
        InstObj = namedtuple('InstObj', ['name', 'image', 'cpu', 'memory'])
        inst_objects = [InstObj(**i) for i in exported_instances]
        
        hcl_content = self._generate_hcl(target_network, inst_objects)
        
        # 2. Загружаем в Supabase
        file_name = f"exported_{project_name}_{uuid.uuid4().hex[:6]}.tf"
        file_bytes = hcl_content.encode('utf-8')
        storage_path = f"configs/{file_name}"

        try:
            supabase.storage.from_("terraform-files").upload(
                path=storage_path,
                file=file_bytes,
                file_options={"content-type": "text/plain"}
            )
            public_url = supabase.storage.from_("terraform-files").get_public_url(storage_path)
            return public_url, hcl_content
        except Exception as e:
            raise Exception(f"Export upload error: {str(e)}")
    
    def deploy_raw_hcl(self, project_name: str, hcl_content: str):
        """Развертывание из готового HCL (Terraform) кода"""
        project_path = self.BASE_DIR / project_name
        project_path.mkdir(exist_ok=True, parents=True)

        # Сохраняем присланный код в main.tf
        with open(project_path / "main.tf", "w") as f:
            f.write(hcl_content)

        # Стандартный цикл запуска
        self.run_command(["terraform", "init"], cwd=project_path)
        output = self.run_command(["terraform", "apply", "-auto-approve"], cwd=project_path)
        return output