import bcrypt
import sentry_sdk
import os
import jwt
from dotenv import load_dotenv
from supabase import create_client, Client
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from datetime import datetime, timedelta, timezone
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi import Depends

load_dotenv()

url: str = os.environ.get("SUPABASE_URL")
key: str = os.environ.get("SUPABASE_KEY")
supabase: Client = create_client(url, key)
SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30


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

class RegistroCreate(BaseModel):
    id_usuario: int
    hora_inicio: str
    hora_final: str
    fecha: str
    calidad: int

seguridad = HTTPBearer()

def verificar_token(credenciales: HTTPAuthorizationCredentials = Depends(seguridad)):
    token = credenciales.credentials
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return int(payload["sub"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expirado")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Token inválido")

@app.get("/")
def root():
    return {"mensaje": "API de sleep-tracker-lab funcionando"}

@app.post("/usuarios")
def crear_usuario(usuario: UsuarioCreate):
    datos = usuario.model_dump()
    
    contrasena_bytes = datos["contrasena"].encode("utf-8")
    hash_bytes = bcrypt.hashpw(contrasena_bytes, bcrypt.gensalt())
    datos["contrasena"] = hash_bytes.decode("utf-8")
    
    response = supabase.table("usuario").insert(datos).execute()
    return response.data

@app.get("/registros")
def listar_registros():
    response = supabase.table("registro_sueno").select("*, usuario(nombre, apellido)").execute()
    return response.data

@app.post("/registros")
def crear_registro(registro: RegistroCreate, usuario_actual: int = Depends(verificar_token)):
    datos = registro.model_dump()
    
    formato = "%H:%M:%S"
    inicio = datetime.strptime(datos["hora_inicio"], formato)
    final = datetime.strptime(datos["hora_final"], formato)
    
    diferencia = final - inicio
    if diferencia.total_seconds() < 0:
        diferencia += timedelta(days=1)
    
    duracion_horas = diferencia.total_seconds() / 3600
    datos["duracion"] = round(duracion_horas, 2)
    
    response = supabase.table("registro_sueno").insert(datos).execute()
    return response.data

class UsuarioLogin(BaseModel):
    email: str
    contrasena: str

@app.post("/login")
def login(credenciales: UsuarioLogin):
    response = supabase.table("usuario").select("*").eq("email", credenciales.email).execute()
    
    if not response.data:
        raise HTTPException(status_code=401, detail="Credenciales inválidas")
    
    usuario_db = response.data[0]
    
    contrasena_bytes = credenciales.contrasena.encode("utf-8")
    hash_guardado = usuario_db["contrasena"].encode("utf-8")
    
    if not bcrypt.checkpw(contrasena_bytes, hash_guardado):
        raise HTTPException(status_code=401, detail="Credenciales inválidas")
    
    expiracion = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub": str(usuario_db["id_usuario"]),
        "exp": expiracion
    }
    token = jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)
    
    return {"access_token": token, "token_type": "bearer"}