"""Matriz de permisos por rol. ÚNICO lugar donde se decide quién puede qué.

Reto 2 (cambio de permisos): agregar o quitar un rol del conjunto de una acción
y reiniciar el servicio web:  docker compose restart web
"""
from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied

PERMISOS = {
    "subir":              {"usuario", "operador", "admin"},
    "ver_todos":          {"operador", "admin"},
    "descargar_ajeno":    {"admin"},
    "reintentar":         {"operador", "admin"},
    "eliminar":           {"admin"},
    "gestionar_usuarios": {"admin"},
    "ver_auditoria":      {"admin"},
}


def rol_de(user):
    if not user or not user.is_authenticated:
        return None
    perfil = getattr(user, "perfil", None)
    return perfil.rol if perfil else "usuario"


def puede(user, accion):
    if accion not in PERMISOS:
        raise KeyError(f"Acción desconocida en la matriz: {accion}")
    return rol_de(user) in PERMISOS[accion]


def requiere(accion):
    """Decorador para vistas: exige sesión y permiso. Si no lo tiene: 403 + auditoría."""

    def decorador(vista):
        @login_required
        @wraps(vista)
        def envoltura(request, *args, **kwargs):
            if not puede(request.user, accion):
                from .auditoria import auditar

                auditar(request, "ACCESO_DENEGADO", objeto=request.path, permitido=False,
                        detalle=f"permiso requerido: {accion}")
                raise PermissionDenied
            return vista(request, *args, **kwargs)

        return envoltura

    return decorador
