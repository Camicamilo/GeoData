"""Validación de entrada (en el API) y procesamiento (en el worker) de los CSV de muestras de suelo."""
import csv
import hashlib
import io
import math
import statistics
from pathlib import Path

from django.conf import settings

COLUMNAS = ["muestra_id", "ph", "humedad", "nitrogeno", "fosforo"]
NUMERICAS = COLUMNAS[1:]
RANGOS = {"ph": (0, 14), "humedad": (0, 100), "nitrogeno": (0, 10_000), "fosforo": (0, 10_000)}
EXTENSIONES = {".csv"}


class ArchivoRechazado(Exception):
    """El archivo no cumple la política de entrada: no entra a la cola."""


class ErrorProcesamiento(Exception):
    """El archivo se aceptó pero su contenido no es válido: el trabajo queda FALLIDO."""


# ---------------------------------------------------------------- API ------
def validar_entrada(nombre, contenido: bytes):
    """Política de entrada: .csv, ≤ MAX_UPLOAD_BYTES, texto UTF-8 sin bytes nulos."""
    if Path(nombre).suffix.lower() not in EXTENSIONES:
        raise ArchivoRechazado(f"Extensión no permitida ({Path(nombre).suffix or 'sin extensión'}); solo .csv")
    if len(contenido) == 0:
        raise ArchivoRechazado("Archivo vacío")
    if len(contenido) > settings.MAX_UPLOAD_BYTES:
        raise ArchivoRechazado(
            f"Tamaño {len(contenido)} B supera el máximo de {settings.MAX_UPLOAD_BYTES} B"
        )
    if b"\x00" in contenido:
        raise ArchivoRechazado("Contenido binario: no es un CSV de texto")
    try:
        contenido.decode("utf-8")
    except UnicodeDecodeError:
        raise ArchivoRechazado("El archivo no es texto UTF-8 (¿PDF o binario renombrado?)")


# ------------------------------------------------------------- WORKER ------
def procesar(ruta: Path) -> dict:
    datos = ruta.read_bytes()
    sha256 = hashlib.sha256(datos).hexdigest()
    lector = csv.reader(io.StringIO(datos.decode("utf-8")))

    encabezado = next(lector, None)
    if encabezado is None:
        raise ErrorProcesamiento("CSV vacío")
    encabezado = [c.strip().lower() for c in encabezado]
    if encabezado != COLUMNAS:
        raise ErrorProcesamiento(f"Encabezado inválido: {encabezado}. Se esperaba {COLUMNAS}")

    valores = {c: [] for c in NUMERICAS}
    filas = 0
    for n, fila in enumerate(lector, start=2):
        if not fila or all(not c.strip() for c in fila):
            continue
        if len(fila) != len(COLUMNAS):
            raise ErrorProcesamiento(f"Fila {n}: {len(fila)} columnas, se esperaban {len(COLUMNAS)}")
        for col, crudo in zip(NUMERICAS, fila[1:]):
            try:
                v = float(crudo)
            except ValueError:
                raise ErrorProcesamiento(f"Fila {n}, columna '{col}': '{crudo}' no es numérico")
            lo, hi = RANGOS[col]
            if math.isnan(v) or not lo <= v <= hi:
                raise ErrorProcesamiento(f"Fila {n}, columna '{col}': {v} fuera de rango [{lo}, {hi}]")
            valores[col].append(v)
        filas += 1

    if filas == 0:
        raise ErrorProcesamiento("El CSV no tiene filas de datos")

    return {
        "sha256": sha256,
        "bytes": len(datos),
        "filas": filas,
        "estadisticas": {
            col: {
                "min": min(vs),
                "max": max(vs),
                "media": round(statistics.fmean(vs), 4),
                "desviacion": round(statistics.pstdev(vs), 4),
            }
            for col, vs in valores.items()
        },
    }


# -------------------------------------------------------- ALMACENAMIENTO ---
def dir_usuario(user_id, sub):
    """Datos separados por usuario: MEDIA_ROOT/<user_id>/{originales,resultados}/"""
    d = Path(settings.MEDIA_ROOT) / str(user_id) / sub
    d.mkdir(parents=True, exist_ok=True, mode=0o750)
    return d
