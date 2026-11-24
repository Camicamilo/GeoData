from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.dispatch import receiver

from .auditoria import auditar


@receiver(user_logged_in)
def login_ok(sender, request, user, **kwargs):
    auditar(request, "LOGIN_OK", usuario=user)


@receiver(user_logged_out)
def logout(sender, request, user, **kwargs):
    if user:
        auditar(request, "LOGOUT", usuario=user)


@receiver(user_login_failed)
def login_fallido(sender, credentials, request=None, **kwargs):
    auditar(request, "LOGIN_FALLIDO", permitido=False, username=credentials.get("username", "?")[:150])
