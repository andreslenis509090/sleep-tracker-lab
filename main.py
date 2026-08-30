import bcrypt
import sentry_sdk
import os
import jwt
from dotenv import load_dotenv
from supabase import create_client, Client
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from datetime import datetime, timedelta, timezone, date
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

    if not datos["hora_inicio"].strip():
        raise HTTPException(status_code=400, detail="La hora es obligatoria")

    formato = "%H:%M:%S"
    try:
        inicio = datetime.strptime(datos["hora_inicio"], formato)
        final = datetime.strptime(datos["hora_final"], formato)
    except ValueError:
        raise HTTPException(status_code=400, detail="Formato de hora no válido")

    fecha_hora_inicio = datetime.strptime(datos["fecha"] + " " + datos["hora_inicio"], "%Y-%m-%d %H:%M:%S")
    if fecha_hora_inicio > datetime.now():
        raise HTTPException(status_code=400, detail="No se puede registrar un inicio de sueño en el futuro")

    diferencia = final - inicio
    if diferencia.total_seconds() < 0:
        diferencia += timedelta(days=1)

    duracion_horas = diferencia.total_seconds() / 3600
    datos["duracion"] = round(duracion_horas, 2)

    response = supabase.table("registro_sueno").insert(datos).execute()
    return response.data

@app.get("/metricas")
def obtener_metricas(offset_semanas: int = 0, usuario_actual: int = Depends(verificar_token)):
    hoy = date.today()
    lunes_actual = hoy - timedelta(days=hoy.weekday())
    lunes_semana = lunes_actual - timedelta(weeks=offset_semanas)
    domingo_semana = lunes_semana + timedelta(days=6)

    response = supabase.table("registro_sueno").select("fecha, duracion, calidad").eq("id_usuario", usuario_actual).gte("fecha", lunes_semana.isoformat()).lte("fecha", domingo_semana.isoformat()).execute()

    registros_por_fecha = {r["fecha"]: r for r in response.data}

    dias = []
    for i in range(7):
        fecha_dia = lunes_semana + timedelta(days=i)
        fecha_str = fecha_dia.isoformat()
        registro = registros_por_fecha.get(fecha_str)
        dias.append({
            "fecha": fecha_str,
            "horas": registro["duracion"] if registro else None,
            "calidad": registro["calidad"] if registro else None,
            "critico": registro is not None and registro["duracion"] < 6
        })

    horas_validas = [d["horas"] for d in dias if d["horas"] is not None]
    promedio = round(sum(horas_validas) / len(horas_validas), 1) if horas_validas else None

    return {
        "semana_inicio": lunes_semana.isoformat(),
        "semana_fin": domingo_semana.isoformat(),
        "dias": dias,
        "promedio_semanal": promedio,
        "tiene_datos": len(horas_validas) > 0
    }

class AlertaCreate(BaseModel):
    hora_recordatorio: str
    tipo: str

TIPOS_VALIDOS = {"dormir", "despertar"}

@app.post("/alertas")
def crear_alerta(alerta: AlertaCreate, usuario_actual: int = Depends(verificar_token)):
    datos = alerta.model_dump()

    if datos["tipo"] not in TIPOS_VALIDOS:
        raise HTTPException(status_code=400, detail="El tipo debe ser 'dormir' o 'despertar'")

    formato = "%H:%M:%S"
    try:
        datetime.strptime(datos["hora_recordatorio"], formato)
    except ValueError:
        raise HTTPException(status_code=400, detail="Formato de hora no válido")

    existente = supabase.table("alerta").select("id_alerta").eq("id_usuario", usuario_actual).eq("tipo", datos["tipo"]).eq("hora_recordatorio", datos["hora_recordatorio"]).eq("estado", True).execute()

    if existente.data:
        raise HTTPException(status_code=409, detail="Ya existe una alerta activa idéntica para esa hora y tipo")

    datos["id_usuario"] = usuario_actual
    datos["estado"] = True

    response = supabase.table("alerta").insert(datos).execute()
    return response.data


@app.get("/alertas")
def listar_alertas(usuario_actual: int = Depends(verificar_token)):
    response = supabase.table("alerta").select("*").eq("id_usuario", usuario_actual).execute()
    return response.data


class AlertaUpdate(BaseModel):
    hora_recordatorio: str

@app.put("/alertas/{id_alerta}")
def actualizar_alerta(id_alerta: int, cambio: AlertaUpdate, usuario_actual: int = Depends(verificar_token)):
    alerta = supabase.table("alerta").select("id_usuario").eq("id_alerta", id_alerta).execute()

    if not alerta.data:
        raise HTTPException(status_code=404, detail="Alerta no encontrada")

    if alerta.data[0]["id_usuario"] != usuario_actual:
        raise HTTPException(status_code=403, detail="No puedes modificar alertas de otro usuario")

    formato = "%H:%M:%S"
    try:
        datetime.strptime(cambio.hora_recordatorio, formato)
    except ValueError:
        raise HTTPException(status_code=400, detail="Formato de hora no válido")

    response = supabase.table("alerta").update({"hora_recordatorio": cambio.hora_recordatorio}).eq("id_alerta", id_alerta).execute()
    return response.data


@app.delete("/alertas/{id_alerta}")
def desactivar_alerta(id_alerta: int, usuario_actual: int = Depends(verificar_token)):
    alerta = supabase.table("alerta").select("id_usuario").eq("id_alerta", id_alerta).execute()

    if not alerta.data:
        raise HTTPException(status_code=404, detail="Alerta no encontrada")

    if alerta.data[0]["id_usuario"] != usuario_actual:
        raise HTTPException(status_code=403, detail="No puedes desactivar alertas de otro usuario")

    supabase.table("alerta").update({"estado": False}).eq("id_alerta", id_alerta).execute()
    return {"mensaje": "Alerta desactivada correctamente"}


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

@app.delete("/registros/{id_registro}")
def eliminar_registro(id_registro: int, usuario_actual: int = Depends(verificar_token)):
    registro = supabase.table("registro_sueno").select("id_usuario").eq("id_registro", id_registro).execute()

    if not registro.data:
        raise HTTPException(status_code=404, detail="Registro no encontrado")

    if registro.data[0]["id_usuario"] != usuario_actual:
        raise HTTPException(status_code=403, detail="No puedes eliminar registros de otro usuario")

    supabase.table("recomendacion").delete().eq("id_registro", id_registro).execute()
    supabase.table("registro_sueno").delete().eq("id_registro", id_registro).execute()

    return {"mensaje": "Registro eliminado correctamente"}

@app.delete("/usuarios/{id_usuario}")
def eliminar_usuario(id_usuario: int, usuario_actual: int = Depends(verificar_token)):
    if id_usuario != usuario_actual:
        raise HTTPException(status_code=403, detail="Solo puedes eliminar tu propia cuenta")

    registros = supabase.table("registro_sueno").select("id_registro").eq("id_usuario", id_usuario).execute()

    for registro in registros.data:
        supabase.table("recomendacion").delete().eq("id_registro", registro["id_registro"]).execute()

    supabase.table("registro_sueno").delete().eq("id_usuario", id_usuario).execute()
    supabase.table("alerta").delete().eq("id_usuario", id_usuario).execute()
    supabase.table("usuario").delete().eq("id_usuario", id_usuario).execute()

    return {"mensaje": "Usuario y sus datos asociados eliminados correctamente"}