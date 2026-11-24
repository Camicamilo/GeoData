"""Crea las cuentas de demostración (datos sintéticos).

La contraseña sale de DEMO_PASSWORD (.env), nunca del código.
    docker compose exec web python manage.py seed_demo
"""
import os

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import Perfil, Rol

CUENTAS = [("jefe", Rol.ADMIN), ("analista", Rol.OPERADOR)] + [(f"tecnico{i}", Rol.USUARIO) for i in range(1, 11)]


class Command(BaseCommand):
    help = "Crea jefe (admin), analista (operador) y tecnico1..10 (usuario)"

    def handle(self, *args, **opts):
        password = os.environ.get("DEMO_PASSWORD")
        if not password or len(password) < 10:
            raise CommandError("Define DEMO_PASSWORD (≥10 caracteres) en .env")
        creados = 0
        with transaction.atomic():
            for username, rol in CUENTAS:
                user, nuevo = User.objects.get_or_create(username=username)
                if nuevo:
                    user.set_password(password)
                    user.save()
                    creados += 1
                Perfil.objects.update_or_create(user=user, defaults={"rol": rol})
        self.stdout.write(self.style.SUCCESS(
            f"{creados} cuentas nuevas. Cuentas: " + ", ".join(f"{u} ({r})" for u, r in CUENTAS)))
