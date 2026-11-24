# AgroLab Sugamuxi: plataforma segura de procesamiento en la nube

Proyecto final de **Sistemas Operativos**, UPTC-FSS, 2026.

AgroLab Sugamuxi es un laboratorio **ficticio** de análisis de suelos. Los técnicos de campo suben archivos CSV con las mediciones de sus muestras, y un trabajador en segundo plano calcula estadísticas por variable. Todos los datos son sintéticos.

## Arquitectura

```
Internet ──► Security Group (80, 443; 22 solo IP del equipo)
              │
         EC2 Ubuntu 24.04 · Docker
              │
   red frontend │ ┌───────── red backend (internal: sin salida a internet) ─────────┐
   nginx :80/:443 ──► web (Django+gunicorn) ──► db (PostgreSQL 16) ◄── worker (x N)  │
   (TLS, proxy)     │        │                    ▲ cola: SELECT … FOR UPDATE      │
                    │        └── vol media ◄──────┼── SKIP LOCKED                   │
                    └─────────────────── vol pgdata┘                                │
```

| Servicio | Función | Puertos publicados | Usuario |
|---|---|---|---|
| `nginx` | Proxy inverso, TLS, redirección 80→443 y límite de intentos de login | **80, 443** (los únicos) | nginx (101) |
| `web` | Login, roles, subida, consulta, descarga, gestión y auditoría | ninguno | app (1000) |
| `worker` | Toma los trabajos pendientes y los procesa (límite: **0,5 CPU / 256 MB**) | ninguno | app (1000) |
| `db` | Usuarios, trabajos (que además son la cola) y auditoría | **ninguno** | postgres |

**Modelo de servicio: IaaS (EC2).** El curso evalúa el sistema operativo: usuarios, permisos, SSH, procesos y recursos. Un PaaS los ocultaría.

**Decisión de arquitectura (sello).** La cola de trabajos vive en PostgreSQL y no en Redis. El estado y la cola son el mismo registro, así que no se pueden desincronizar. La durabilidad la da la base de datos, hay un servicio menos que asegurar, y `SKIP LOCKED` permite correr varios workers sin que dos tomen el mismo trabajo. El costo es que el worker consulta la tabla cada 1 s, lo que la hace inadecuada para volúmenes muy altos.

## Despliegue

### En AWS Academy (EC2)

1. **Lanzar la instancia:** Ubuntu Server 24.04, `t3.small` (2 GB), 20 GB de disco y la llave `.pem` del lab.
2. **Security Group:** entrada 80 y 443 desde `0.0.0.0/0`, y 22 **solo desde tu IP** (`x.x.x.x/32`). Nada más.
3. Copiar el proyecto y endurecer el servidor:
   ```bash
   scp -i llave.pem -r agrolab ubuntu@IP:~
   ssh -i llave.pem ubuntu@IP
   sudo bash agrolab/scripts/hardening.sh
   sudo mv agrolab/* agrolab/.[!.]* /opt/agrolab/ && sudo chown -R deploy:deploy /opt/agrolab
   sudo -iu deploy
   ```
4. Configurar los secretos y levantar los servicios:
   ```bash
   cd /opt/agrolab
   cp .env.example .env && chmod 600 .env
   nano .env            # cambiar las claves; TLS_CN=<IP pública>
   docker compose up -d --build
   docker compose exec web python manage.py seed_demo
   ```
5. Abrir `https://IP`. El certificado es autofirmado, así que el navegador muestra una advertencia: hay que aceptarla.

> Al reiniciar el Learner Lab, **la IP pública cambia**. Los datos sobreviven porque están en EBS y en volúmenes de Docker. Después de reiniciar: `cd /opt/agrolab && docker compose up -d`.

### En local (para desarrollar)

Se necesita Docker Desktop:

```bash
cp .env.example .env    # cambiar valores
docker compose up -d --build
docker compose exec web python manage.py seed_demo
# https://localhost
```

### Cuentas demo

La contraseña de todas es `DEMO_PASSWORD` del `.env`.

| Usuario | Rol |
|---|---|
| `jefe` | Administrador |
| `analista` | Operador |
| `tecnico1` … `tecnico10` | Usuario |

## Roles y regla de negocio

La matriz vive en un solo archivo, `app/core/permisos.py`:

| Acción | Usuario | Operador | Admin |
|---|:-:|:-:|:-:|
| Subir y ver/descargar **sus** trabajos | ✅ | ✅ | ✅ |
| Ver el estado de **todos** los trabajos | ❌ | ✅ | ✅ |
| Reintentar trabajos fallidos | ❌ | ✅ | ✅ |
| Descargar resultados de **otros** | ❌ | ❌ | ✅ |
| Eliminar trabajos | ❌ | ❌ | ✅ |
| Gestionar usuarios y roles, ver auditoría | ❌ | ❌ | ✅ |

- **Aislamiento:** toda consulta pasa por `Job.objects.visibles_para(user)` o `descargables_para(user)`. Si alguien pide el trabajo de otro, recibe un **404** (no un 403, para no confirmar que el ID existe) y el intento queda auditado como `ACCESO_DENEGADO`. Los IDs son UUID, así que no se pueden adivinar. Nginx nunca sirve `/media`: toda descarga pasa por Django, que verifica al dueño.
- **Regla de negocio (cuota):** un usuario puede tener como máximo `MAX_TRABAJOS_ACTIVOS` = **3** trabajos pendientes o en ejecución. El cuarto se responde con **429** y se audita como `CUOTA_EXCEDIDA`. La verificación bloquea la fila del perfil (`select_for_update`), así que dos subidas simultáneas del mismo usuario no pueden saltarse la cuota.

## Procesamiento

| Etapa | Dónde | Qué valida o hace |
|---|---|---|
| Entrada | API, antes de la cola | `.csv`, ≤ 2 MB, UTF-8 sin bytes nulos. Si no cumple: **400** y `RECHAZO_ARCHIVO` |
| Cola | `estado = pendiente` | La petición HTTP responde de inmediato (asíncrono) |
| Worker | `en_ejecucion` | Encabezado `muestra_id,ph,humedad,nitrogeno,fosforo`, valores numéricos y rangos (pH 0–14, humedad 0–100) |
| Resultado | `completado` / `fallido` | JSON con SHA-256, número de filas y min/max/media/desviación por variable. Si falla, guarda el error |

Almacenamiento separado por usuario: `/data/media/<user_id>/{originales,resultados}/`, con archivos `640` y directorios `750`.

## Dataset propio

Se genera con `python3 scripts/generar_dataset.py`. La semilla es fija, así que el resultado es reproducible.

| Archivo | Tamaño | Resultado esperado |
|---|---|---|
| `muestras_finca_a.csv` | 2,9 KB | completado |
| `muestras_valle_completo.csv` | 1,1 MB | completado (prueba de carga) |
| `muestras_encabezado_malo.csv` | 1,5 KB | **fallido**: encabezado inválido |
| `muestras_ph_texto.csv` | 2,3 KB | **fallido**: "acido" en la fila 40 |
| `informe_renombrado.csv` | 50 KB | **rechazado**: binario |
| `muestras_gigante.csv` | 2,3 MB | **rechazado**: tamaño |

## Seguridad y hardening

| # | Medida | Evidencia |
|---|---|---|
| 1 | Contenedores **sin root**: `USER app`, `nginx-unprivileged` | `docker compose exec web id` |
| 2 | `cap_drop: ALL`, `no-new-privileges` y **sistema de archivos de solo lectura** (`read_only`) | `docker inspect` |
| 3 | El código de la app es de root y no se puede escribir: la app no puede modificarse a sí misma | `docker compose exec web touch /app/x` falla |
| 4 | Solo nginx publica puertos. La red `backend` es `internal`, así que db, web y worker no tienen salida a internet | `docker compose ps`, `ss -tlnp` |
| 5 | Security Group: 80/443 público y 22 solo desde la IP del equipo | consola AWS |
| 6 | SSH solo con llave, sin root y con `MaxAuthTries 3` | `sudo sshd -T` |
| 7 | Usuario `deploy` sin sudo. `/opt/agrolab` en `750` y `.env` en `600` | `ls -l` |
| 8 | Actualizaciones automáticas (`unattended-upgrades`) y servicios innecesarios deshabilitados | `systemctl` |
| 9 | Contraseñas con hash **PBKDF2-SHA256** (Django), mínimo 10 caracteres | tabla `auth_user` |
| 10 | TLS, cookies `Secure`/`HttpOnly`/`SameSite`, CSRF, sesión de 1 h y límite de 10 intentos de login por minuto | navegador |
| 11 | Sin panel `/admin` de Django: no está instalado y nginx bloquea esa ruta | `curl -k https://IP/admin` devuelve 404 |
| 12 | Secretos solo en `.env`, que no se versiona | `git ls-files` |

**Todas las evidencias de una vez:** `bash scripts/evidencias.sh`

## Pruebas

```bash
docker compose exec web python manage.py test core          # 18 pruebas automáticas
python3 scripts/carga.py --url https://IP --inseguro --password "<DEMO_PASSWORD>"
docker compose up -d --scale worker=3                       # repetir la carga con 3 workers
```

Las pruebas automáticas cubren: hash de contraseñas, 3 roles con privilegios estrictamente crecientes, denegaciones auditadas, aislamiento (ver, descargar y consultar el estado de un trabajo ajeno), el ciclo asíncrono completo, los estados fallido y rechazado, la cuota, el reintento del operador y la recuperación de trabajos huérfanos.

Resultados de referencia de la carga (30 trabajos de 1,1 MB, 10 usuarios, sin contenedores):

| Workers | Tiempo total | Throughput | Trabajos duplicados |
|---|---|---|---|
| 1 | 14,3 s | 2,1 trabajos/s | 0 |
| 3 | 6,1 s | 4,9 trabajos/s | 0 (`max(intentos) = 1`) |

En la EC2 hay que repetir la medición con el límite de 0,5 CPU activo y anotar lo que muestre `docker stats`.

## Observabilidad y recuperación

- `docker compose ps`, `docker stats`, `free -h`, `df -h` y `htop`.
- `docker compose logs -f worker`: cada trabajo deja el usuario, el archivo, el estado y la duración.
- **Recuperación:**
  - Todos los servicios usan `restart: unless-stopped`.
  - Con `docker compose stop worker` (SIGTERM), el worker termina el trabajo actual y sale limpio.
  - Si el worker muere a mitad de un trabajo, al reiniciar (y cada 30 s) los trabajos que llevan en ejecución más de `WORKER_TIMEOUT_SECONDS` vuelven a pendiente.
- **Persistencia:** después de `docker compose down && docker compose up -d` los datos siguen ahí. Solo `down -v` borra los volúmenes.

## Retos de la sustentación: dónde se toca cada cosa

| Reto | Cómo |
|---|---|
| 1. Nuevo usuario | `/gestion/usuarios/` o `docker compose exec web python manage.py crear_usuario pepe usuario`. Después, entrar como pepe a `/gestion/usuarios/` da **403** |
| 2. Cambio de permisos | `app/core/permisos.py`: agregar `"operador"` a la acción. Luego `docker compose up -d --build web` y probar con analista (✅) y con un técnico (❌) |
| 3. Aislamiento | `app/core/models.py` → `JobQuerySet.visibles_para`/`descargables_para`: el `filter(owner=user)` |
| 4. Recursos | `docker-compose.yml` → `cpus` y `mem_limit` del worker. Luego `docker compose up -d worker` y `docker stats --no-stream` |
| 5. Recuperación | `docker compose stop worker`, subir un archivo (queda pendiente), `docker compose start worker` y `docker compose logs -f worker` |
| 6. Auditoría | En la vista, `auditar(request, "ACCION", objeto=f"job:{job.id}")`. Aparece en `/gestion/auditoria/` |

> El código se copia dentro de la imagen, así que **cualquier cambio en `app/` requiere** `docker compose up -d --build web worker`.

## Estructura

```
docker-compose.yml   .env.example   nginx/   scripts/   dataset/
app/
├── Dockerfile  entrypoint.sh  requirements.txt  manage.py
├── agrolab/settings.py  urls.py
└── core/
    ├── permisos.py       matriz de roles + decorador @requiere
    ├── models.py         Perfil, Job (+ aislamiento), EventoAuditoria
    ├── views.py          subir, detalle, descargar, gestión, auditoría
    ├── procesamiento.py  validación de entrada + procesamiento CSV
    ├── auditoria.py      auditar()
    ├── management/commands/  worker · crear_usuario · seed_demo
    └── tests.py
```

## Limitaciones conocidas

- **Docker se salta UFW:** los puertos publicados no pasan por las reglas de `ufw`, porque Docker escribe directamente en iptables. El control efectivo es el Security Group, sumado a no publicar puertos internos.
- **El grupo `docker` equivale a root:** `deploy` puede escalar privilegios a través de Docker. Lo ideal sería Docker *rootless*, que quedó fuera por tiempo.
- **Certificado autofirmado:** cifra el tráfico, pero no autentica el servidor, porque AWS Academy no da dominio para pedir uno real.
- **Cola por polling:** la latencia es de hasta 1 s y no está pensada para miles de trabajos por segundo.
- **Un solo nodo:** si la EC2 se cae, el servicio se cae. No hay alta disponibilidad.
- **`WORKER_DEMORA_SECONDS`:** es una pausa artificial para que los estados se vean durante la demo. Se pone en 0 para las mediciones reales.
