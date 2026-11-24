"""Crea un usuario con rol (reto 1 por consola).

    docker compose exec web python manage.py crear_usuario pepe usuario
    (pide la contraseña sin mostrarla)
"""
import getpass

from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.auditoria import auditar
from core.models import Perfil, Rol


class Command(BaseCommand):
    help = "Crea un usuario con su rol"

    def add_arguments(self, parser):
        parser.add_argument("username")
        parser.add_argument("rol", choices=Rol.values)
        parser.add_argument("--password", help="Si no se da, se pide por consola")

    def handle(self, username, rol, password=None, **opts):
        if User.objects.filter(username=username).exists():
            raise CommandError(f"El usuario {username} ya existe")
        password = password or getpass.getpass("Contraseña: ")
        try:
            validate_password(password, User(username=username))
        except ValidationError as e:
            raise CommandError("Contraseña débil: " + " ".join(e.messages))
        with transaction.atomic():
            user = User.objects.create_user(username=username, password=password)
            Perfil.objects.create(user=user, rol=rol)
        auditar(None, "CREACION_USUARIO", objeto=f"user:{username}", detalle=f"rol={rol} (consola)",
                username="consola")
        self.stdout.write(self.style.SUCCESS(f"Usuario {username} creado con rol {rol}"))
