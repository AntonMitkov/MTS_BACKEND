import pylxd

try:
    client = pylxd.Client()
except Exception as e:
    print(f"Критическая ошибка: Нет доступа к LXD: {e}")
    client = None