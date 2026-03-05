from supabase import create_client, Client
from dotenv import load_dotenv
import os

load_dotenv()

SUPABASE_URL = "https://uzwckwgitwfpfpmzmfvr.supabase.co"
SUPABASE_KEY = os.getenv('SUPABASE_API') # Используй service_role для прав на запись

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)