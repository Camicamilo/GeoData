"""Registro de auditoría: quién, qué, sobre qué, resultado, desde dónde y cuándo.

Se guarda en la tabla EventoAuditoria (consultable en /gestion/auditoria/) y además
se escribe en el log del contenedor (docker compose logs web).

Reto 6: para auditar una acción nueva basta con llamar
    auditar(request, "NOMBRE_ACCION", objeto=algo, permitido=True)
"""
import logging

from .models import EventoAuditoria

log = logging.getLogger("auditoria")


def ip_de(request):
    if request is None:
        return None
    # nginx es el único que llega a web y fija X-Real-IP; si no está, IP directa
    return request.META.get("HTTP_X_REAL_IP") or request.META.get("REMOTE_ADDR")


def auditar(request, accion, objeto="", permitido=True, detalle="", usuario=None, username=None):
    if usuario is None and request is not None and request.user.is_authenticated:
        usuario = request.user
    nombre = username or (usuario.username if usuario else "anonimo")
    resultado = EventoAuditoria.PERMITIDO if permitido else EventoAuditoria.DENEGADO
    evento = EventoAuditoria.objects.create(
        usuario=usuario,
        username=nombre,
        accion=accion,
        objeto=str(objeto)[:255],
        resultado=resultado,
        ip=ip_de(request),
        detalle=str(detalle)[:500],
    )
    log.info("usuario=%s accion=%s objeto=%s resultado=%s ip=%s detalle=%s",
             nombre, accion, evento.objeto, resultado, evento.ip, evento.detalle)
    return evento
