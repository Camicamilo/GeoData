import json
import logging
import os
from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count, Max
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .auditoria import auditar
from .models import Estado, EventoAuditoria, Job, Perfil, Rol
from .permisos import requiere
from .procesamiento import ArchivoRechazado, dir_usuario, validar_entrada

log = logging.getLogger("web")


def healthz(request):
    return HttpResponse("ok", content_type="text/plain")


def prohibido(request, exception=None):
    return render(request, "core/error.html", {"codigo": 403, "mensaje": "No tienes permiso para esto."}, status=403)


def no_encontrado(request, exception=None):
    return render(request, "core/error.html", {"codigo": 404, "mensaje": "No existe."}, status=404)


def _job_visible_o_404(request, job_id, consulta="visibles_para"):
    """Busca el trabajo SOLO entre los permitidos. Si existe pero es ajeno: audita y responde 404
    (no 403, para no confirmar que el ID existe)."""
    permitidos = getattr(Job.objects, consulta)(request.user)
    try:
        return permitidos.get(pk=job_id)
    except Job.DoesNotExist:
        if Job.objects.filter(pk=job_id).exists():
            auditar(request, "ACCESO_DENEGADO", objeto=f"job:{job_id}", permitido=False,
                    detalle=f"intento de acceso cruzado ({consulta})")
        raise Http404


# ------------------------------------------------------------ usuario -----
@login_required
def inicio(request):
    jobs = Job.objects.filter(owner=request.user)[:50]
    activos = Job.objects.filter(owner=request.user).activos().count()
    return render(request, "core/inicio.html", {
        "jobs": jobs,
        "activos": activos,
        "max_activos": settings.MAX_TRABAJOS_ACTIVOS,
        "max_mb": settings.MAX_UPLOAD_BYTES / (1024 * 1024),
        "refrescar": activos > 0,
    })


@require_POST
@requiere("subir")
def subir(request):
    archivo = request.FILES.get("archivo")
    if archivo is None:
        messages.error(request, "Selecciona un archivo.")
        return redirect("inicio")

    contenido = archivo.read(settings.MAX_UPLOAD_BYTES + 1)  # nunca leer más del máximo
    try:
        validar_entrada(archivo.name, contenido)
    except ArchivoRechazado as e:
        auditar(request, "RECHAZO_ARCHIVO", objeto=archivo.name, permitido=False, detalle=str(e))
        return render(request, "core/error.html",
                      {"codigo": 400, "mensaje": f"Archivo rechazado: {e}"}, status=400)

    # ==== REGLA DE NEGOCIO: cuota de trabajos activos por usuario ==========
    # select_for_update sobre el perfil serializa las subidas concurrentes del mismo
    # usuario: sin esto, dos peticiones simultáneas podrían pasar ambas el conteo.
    with transaction.atomic():
        Perfil.objects.select_for_update().get_or_create(user=request.user)
        activos = Job.objects.filter(owner=request.user).activos().count()
        if activos >= settings.MAX_TRABAJOS_ACTIVOS:
            auditar(request, "CUOTA_EXCEDIDA", objeto=archivo.name, permitido=False,
                    detalle=f"{activos} trabajos activos (máx {settings.MAX_TRABAJOS_ACTIVOS})")
            return render(request, "core/error.html", {
                "codigo": 429,
                "mensaje": f"Cuota excedida: ya tienes {activos} trabajos activos "
                           f"(máximo {settings.MAX_TRABAJOS_ACTIVOS}). Espera a que terminen.",
            }, status=429)

        job = Job(owner=request.user, nombre_original=archivo.name[:255], tamano_bytes=len(contenido),
                  ruta_original="")
        ruta = dir_usuario(request.user.id, "originales") / f"{job.id}.csv"
        fd = os.open(ruta, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o640)
        with os.fdopen(fd, "wb") as f:
            f.write(contenido)
        job.ruta_original = str(ruta)
        job.save()  # queda PENDIENTE: el worker lo toma (procesamiento desacoplado)

    auditar(request, "SUBIDA", objeto=f"job:{job.id}", detalle=f"{archivo.name} ({len(contenido)} B)")
    messages.success(request, f"'{archivo.name}' recibido. El trabajo quedó pendiente.")
    return redirect("detalle", job_id=job.id)


@login_required
def detalle(request, job_id):
    job = _job_visible_o_404(request, job_id)
    #auditar(request, "DETALLE", objeto=f"job:{job.id}")
    resultado = None
    if job.estado == Estado.COMPLETADO and job.ruta_resultado:
        try:
            resultado = json.loads(Path(job.ruta_resultado).read_text())
        except OSError:
            resultado = None
    puede_descargar = Job.objects.descargables_para(request.user).filter(pk=job.pk).exists()
    return render(request, "core/detalle.html", {
        "job": job, "resultado": resultado, "puede_descargar": puede_descargar,
        "refrescar": job.estado in (Estado.PENDIENTE, Estado.EN_EJECUCION),
    })


@login_required
def estado_json(request, job_id):
    job = _job_visible_o_404(request, job_id)
    return JsonResponse({"id": str(job.id), "estado": job.estado, "error": job.error,
                         "duracion": job.duracion, "worker": job.worker})


@login_required
def descargar(request, job_id):
    # La descarga SIEMPRE pasa por aquí (nginx no sirve /media): se verifica el dueño.
    job = _job_visible_o_404(request, job_id, consulta="descargables_para")
    if job.estado != Estado.COMPLETADO or not job.ruta_resultado:
        raise Http404
    auditar(request, "DESCARGA", objeto=f"job:{job.id}")
    nombre = Path(job.nombre_original).stem + "_resultado.json"
    return FileResponse(open(job.ruta_resultado, "rb"), as_attachment=True, filename=nombre,
                        content_type="application/json")


@require_POST
@requiere("reintentar")
def reintentar(request, job_id):
    job = _job_visible_o_404(request, job_id)
    if job.estado != Estado.FALLIDO:
        messages.error(request, "Solo se pueden reintentar trabajos fallidos.")
        return redirect("detalle", job_id=job.id)
    Job.objects.filter(pk=job.pk, estado=Estado.FALLIDO).update(estado=Estado.PENDIENTE, error="")
    auditar(request, "REINTENTO", objeto=f"job:{job.id}")
    messages.success(request, "Trabajo devuelto a la cola.")
    return redirect("detalle", job_id=job.id)


@require_POST
@requiere("eliminar")
def eliminar(request, job_id):
    job = _job_visible_o_404(request, job_id)
    if job.estado == Estado.EN_EJECUCION:
        messages.error(request, "No se puede eliminar un trabajo en ejecución.")
        return redirect("detalle", job_id=job.id)
    for ruta in (job.ruta_original, job.ruta_resultado):
        if ruta:
            Path(ruta).unlink(missing_ok=True)
    auditar(request, "ELIMINACION", objeto=f"job:{job.id}", detalle=f"{job.nombre_original} de {job.owner.username}")
    job.delete()
    messages.success(request, "Trabajo eliminado.")
    return redirect("todos")


# ----------------------------------------------------------- operador -----
@requiere("ver_todos")
def todos(request):
    jobs = Job.objects.visibles_para(request.user).select_related("owner")
    estado = request.GET.get("estado")
    if estado in Estado.values:
        jobs = jobs.filter(estado=estado)
    resumen = dict(Job.objects.values_list("estado").annotate(n=Count("id")))
    return render(request, "core/todos.html", {
        "jobs": jobs[:200], "estados": Estado.choices, "filtro": estado,
        "resumen": [(v, l, resumen.get(v, 0)) for v, l in Estado.choices],
        "refrescar": True,
    })


# -------------------------------------------------------------- admin -----
@requiere("gestionar_usuarios")
def usuarios(request):
    lista = User.objects.select_related("perfil").annotate(n_jobs=Count("jobs")).order_by("username")
    return render(request, "core/usuarios.html", {"usuarios": lista, "roles": Rol.choices})


@require_POST
@requiere("gestionar_usuarios")
def usuario_nuevo(request):
    username = request.POST.get("username", "").strip()
    password = request.POST.get("password", "")
    rol = request.POST.get("rol", Rol.USUARIO)
    if not username or rol not in Rol.values:
        messages.error(request, "Datos incompletos.")
        return redirect("usuarios")
    if User.objects.filter(username=username).exists():
        messages.error(request, "Ese usuario ya existe.")
        return redirect("usuarios")
    try:
        validate_password(password, User(username=username))
    except ValidationError as e:
        messages.error(request, "Contraseña débil: " + " ".join(e.messages))
        return redirect("usuarios")
    with transaction.atomic():
        user = User.objects.create_user(username=username, password=password)  # se guarda con hash
        Perfil.objects.create(user=user, rol=rol)
    auditar(request, "CREACION_USUARIO", objeto=f"user:{username}", detalle=f"rol={rol}")
    messages.success(request, f"Usuario {username} creado con rol {rol}.")
    return redirect("usuarios")


@require_POST
@requiere("gestionar_usuarios")
def usuario_rol(request, user_id):
    user = get_object_or_404(User, pk=user_id)
    rol = request.POST.get("rol")
    if rol not in Rol.values:
        messages.error(request, "Rol inválido.")
        return redirect("usuarios")
    if user == request.user:
        messages.error(request, "No puedes cambiar tu propio rol.")
        return redirect("usuarios")
    perfil, _ = Perfil.objects.get_or_create(user=user)
    anterior, perfil.rol = perfil.rol, rol
    perfil.save()
    auditar(request, "CAMBIO_ROL", objeto=f"user:{user.username}", detalle=f"{anterior} -> {rol}")
    messages.success(request, f"{user.username}: {anterior} → {rol}")
    return redirect("usuarios")


@require_POST
@requiere("gestionar_usuarios")
def usuario_activo(request, user_id):
    user = get_object_or_404(User, pk=user_id)
    if user == request.user:
        messages.error(request, "No puedes desactivarte a ti mismo.")
        return redirect("usuarios")
    user.is_active = not user.is_active
    user.save(update_fields=["is_active"])
    accion = "ACTIVACION_USUARIO" if user.is_active else "DESACTIVACION_USUARIO"
    auditar(request, accion, objeto=f"user:{user.username}")
    return redirect("usuarios")


@requiere("ver_auditoria")
def auditoria(request):
    eventos = EventoAuditoria.objects.all()
    f = {k: request.GET.get(k, "").strip() for k in ("usuario", "accion", "resultado")}
    if f["usuario"]:
        eventos = eventos.filter(username__icontains=f["usuario"])
    if f["accion"]:
        eventos = eventos.filter(accion=f["accion"])
    if f["resultado"]:
        eventos = eventos.filter(resultado=f["resultado"])
    # Reporte propio (sello de autenticidad): intentos de acceso cruzado/denegado por usuario
    cruzados = (EventoAuditoria.objects.filter(resultado=EventoAuditoria.DENEGADO)
                .values("username").annotate(intentos=Count("id"), ultimo=Max("fecha"))
                .order_by("-intentos")[:20])
    acciones = EventoAuditoria.objects.order_by().values_list("accion", flat=True).distinct()
    return render(request, "core/auditoria.html", {
        "eventos": eventos[:300], "filtros": f, "cruzados": cruzados, "acciones": sorted(set(acciones)),
    })
