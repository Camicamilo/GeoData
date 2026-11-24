from django.contrib.auth import views as auth_views
from django.urls import path

from core import views

urlpatterns = [
    path("accounts/login/", auth_views.LoginView.as_view(template_name="core/login.html"), name="login"),
    path("accounts/logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("healthz", views.healthz, name="healthz"),
    path("", views.inicio, name="inicio"),
    path("jobs/nuevo", views.subir, name="subir"),
    path("jobs/<uuid:job_id>/", views.detalle, name="detalle"),
    path("jobs/<uuid:job_id>/estado.json", views.estado_json, name="estado_json"),
    path("jobs/<uuid:job_id>/descargar", views.descargar, name="descargar"),
    path("jobs/<uuid:job_id>/reintentar", views.reintentar, name="reintentar"),
    path("jobs/<uuid:job_id>/eliminar", views.eliminar, name="eliminar"),
    path("trabajos/", views.todos, name="todos"),
    path("gestion/usuarios/", views.usuarios, name="usuarios"),
    path("gestion/usuarios/nuevo", views.usuario_nuevo, name="usuario_nuevo"),
    path("gestion/usuarios/<int:user_id>/rol", views.usuario_rol, name="usuario_rol"),
    path("gestion/usuarios/<int:user_id>/activo", views.usuario_activo, name="usuario_activo"),
    path("gestion/auditoria/", views.auditoria, name="auditoria"),
]

handler403 = "core.views.prohibido"
handler404 = "core.views.no_encontrado"
