from .permisos import PERMISOS, puede, rol_de


def rol(request):
    user = getattr(request, "user", None)
    return {
        "rol": rol_de(user),
        "puedo": {accion: puede(user, accion) for accion in PERMISOS} if user and user.is_authenticated else {},
    }
