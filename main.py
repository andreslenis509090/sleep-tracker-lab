import sentry_sdk
import os
from dotenv import load_dotenv
from supabase import create_client, Client
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

load_dotenv()

url: str = os.environ.get("SUPABASE_URL")
key: str = os.environ.get("SUPABASE_KEY")
supabase: Client = create_client(url, key)

sentry_sdk.init(
    dsn=os.getenv("SENTRY_DSN"),
    send_default_pii=True,
)

app = FastAPI()

class UsuarioCreate(BaseModel):
    nombre: str
    apellido: str
    ocupacion: str
    meta_sueno: float
    email: str
    contrasena: str

@app.get("/")
def root():
    return {"mensaje": "API de sleep-tracker-lab funcionando"}

@app.post("/usuarios")
def crear_usuario(usuario: UsuarioCreate):
    response = supabase.table("usuario").insert(usuario.model_dump()).execute()
    return response.data

@app.get("/registros")
def listar_registros():
    response = supabase.table("registro_sueno").select("*, usuario(nombre, apellido)").execute()
    return response.data
