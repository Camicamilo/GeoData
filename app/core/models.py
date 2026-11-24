import uuid

from django.conf import settings
from django.db import models


class Rol(models.TextChoices):
    USUARIO = "usuario", "Usuario (técnico de campo)"
    OPERADOR = "operador", "Operador (analista)"
    ADMIN = "admin", "Administrador (jefe de laboratorio)"


class Perfil(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="perfil")
    rol = models.CharField(max_length=10, choices=Rol.choices, default=Rol.USUARIO)

    def __str__(self):
        return f"{self.user.username} ({self.rol})"


class Estado(models.TextChoices):
    PENDIENTE = "pendiente", "Pendiente"
    EN_EJECUCION = "en_ejecucion", "En ejecución"
    COMPLETADO = "completado", "Completado"
    FALLIDO = "fallido", "Fallido"


ESTADOS_ACTIVOS = (Estado.PENDIENTE, Estado.EN_EJECUCION)


class JobQuerySet(models.QuerySet):
    # ==== AISLAMIENTO (reto 3) =============================================
    # Toda consulta de trabajos desde las vistas pasa por estos dos métodos.
    def visibles_para(self, user):
        """Trabajos cuyo estado/metadatos puede ver el usuario."""
        from .permisos import puede

        if puede(user, "ver_todos"):
            return self
        return self.filter(owner=user)

    def descargables_para(self, user):
        """Trabajos cuyo archivo/resultado puede descargar el usuario."""
        from .permisos import puede

        if puede(user, "descargar_ajeno"):
            return self
        return self.filter(owner=user)

    def activos(self):
        return self.filter(estado__in=ESTADOS_ACTIVOS)


class Job(models.Model):
    # UUID y no entero: los IDs no se pueden adivinar ni enumerar
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="jobs")
    nombre_original = models.CharField(max_length=255)
    tamano_bytes = models.PositiveIntegerField()
    ruta_original = models.CharField(max_length=500)
    ruta_resultado = models.CharField(max_length=500, blank=True)
    estado = models.CharField(max_length=15, choices=Estado.choices, default=Estado.PENDIENTE, db_index=True)
    error = models.TextField(blank=True)
    intentos = models.PositiveSmallIntegerField(default=0)
    worker = models.CharField(max_length=100, blank=True)
    creado = models.DateTimeField(auto_now_add=True, db_index=True)
    iniciado = models.DateTimeField(null=True, blank=True)
    terminado = models.DateTimeField(null=True, blank=True)

    objects = JobQuerySet.as_manager()

    class Meta:
        ordering = ["-creado"]
        indexes = [models.Index(fields=["estado", "creado"])]

    def __str__(self):
        return f"{self.nombre_original} [{self.estado}]"

    @property
    def duracion(self):
        if self.iniciado and self.terminado:
            return (self.terminado - self.iniciado).total_seconds()
        return None


class EventoAuditoria(models.Model):
    PERMITIDO, DENEGADO = "PERMITIDO", "DENEGADO"

    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    username = models.CharField(max_length=150)  # se conserva aunque el usuario se elimine
    accion = models.CharField(max_length=40, db_index=True)
    objeto = models.CharField(max_length=255, blank=True)
    resultado = models.CharField(max_length=10, choices=[(PERMITIDO, PERMITIDO), (DENEGADO, DENEGADO)])
    ip = models.GenericIPAddressField(null=True, blank=True)
    detalle = models.CharField(max_length=500, blank=True)
    fecha = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-fecha"]

    def __str__(self):
        return f"{self.fecha:%Y-%m-%d %H:%M:%S} {self.username} {self.accion} {self.resultado}"
