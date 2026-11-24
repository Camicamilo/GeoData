"""Trabajador de procesamiento: toma trabajos PENDIENTES de la cola (tabla Job en PostgreSQL).

Cola sobre la BD con SELECT ... FOR UPDATE SKIP LOCKED:
  - la fila del trabajo queda bloqueada por la transacción de UN worker;
  - otros workers la SALTAN (no esperan ni la duplican) -> se pueden correr varios:
      docker compose up -d --scale worker=3
  - el estado del trabajo y la cola son el mismo registro: no se desincronizan.

Recuperación (reto 5):
  - SIGTERM (docker compose stop) -> termina el trabajo actual y sale limpio.
  - Al arrancar y cada 30 s: los trabajos EN_EJECUCION "huérfanos" (worker murió)
    vuelven a PENDIENTE.
"""
import json
import logging
import os
import signal
import socket
import time
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import OperationalError, close_old_connections, transaction
from django.utils import timezone

from core.models import Estado, Job
from core.procesamiento import ErrorProcesamiento, dir_usuario, procesar

log = logging.getLogger("worker")


class Command(BaseCommand):
    help = "Ejecuta el trabajador de procesamiento de archivos"

    def handle(self, *args, **opts):
        self.nombre = f"{socket.gethostname()}:{os.getpid()}"
        self.detener = False
        signal.signal(signal.SIGTERM, self._senal)
        signal.signal(signal.SIGINT, self._senal)

        log.info("worker %s iniciado (uid=%s, poll=%ss)", self.nombre, os.getuid(), settings.WORKER_POLL_SECONDS)
        ultima_revision = 0.0
        while not self.detener:
            try:
                if time.monotonic() - ultima_revision > 30:
                    self.recuperar_huerfanos()
                    ultima_revision = time.monotonic()
                job = self.tomar_trabajo()
                if job is None:
                    time.sleep(settings.WORKER_POLL_SECONDS)
                    continue
                self.ejecutar(job)
            except OperationalError as e:  # BD caída o reiniciándose: reintentar
                log.warning("BD no disponible (%s); reintento en 3 s", e.__class__.__name__)
                close_old_connections()
                time.sleep(3)
        log.info("worker %s detenido limpiamente", self.nombre)

    def _senal(self, signum, frame):
        log.info("señal %s recibida: termino el trabajo actual y salgo", signal.Signals(signum).name)
        self.detener = True

    def recuperar_huerfanos(self):
        limite = timezone.now() - timedelta(seconds=settings.WORKER_TIMEOUT_SECONDS)
        n = Job.objects.filter(estado=Estado.EN_EJECUCION, iniciado__lt=limite).update(
            estado=Estado.PENDIENTE, worker="")
        if n:
            log.warning("recuperados %s trabajos huérfanos -> pendiente", n)

    def tomar_trabajo(self):
        with transaction.atomic():
            job = (Job.objects.select_for_update(skip_locked=True)
                   .filter(estado=Estado.PENDIENTE).order_by("creado").first())
            if job is None:
                return None
            job.estado = Estado.EN_EJECUCION
            job.iniciado = timezone.now()
            job.terminado = None
            job.intentos += 1
            job.worker = self.nombre
            job.save(update_fields=["estado", "iniciado", "terminado", "intentos", "worker"])
        log.info("job=%s usuario=%s archivo=%s estado=en_ejecucion intento=%s",
                 job.id, job.owner_id, job.nombre_original, job.intentos)
        return job

    def ejecutar(self, job):
        inicio = time.monotonic()
        try:
            if settings.WORKER_DEMORA_SECONDS:
                time.sleep(settings.WORKER_DEMORA_SECONDS)
            resultado = procesar(Path(job.ruta_original))
            resultado.update({"job": str(job.id), "archivo": job.nombre_original,
                              "procesado_por": self.nombre, "procesado_en": timezone.now().isoformat()})
            ruta = dir_usuario(job.owner_id, "resultados") / f"{job.id}.json"
            ruta.write_text(json.dumps(resultado, indent=2, ensure_ascii=False))
            os.chmod(ruta, 0o640)
            job.ruta_resultado, job.estado, job.error = str(ruta), Estado.COMPLETADO, ""
        except ErrorProcesamiento as e:
            job.estado, job.error = Estado.FALLIDO, str(e)
            log.warning("job=%s fallido (contenido inválido): %s", job.id, e)
        except Exception as e:  # error inesperado: queda registrado, el worker sigue vivo
            job.estado, job.error = Estado.FALLIDO, f"Error interno: {e.__class__.__name__}: {e}"
            log.exception("job=%s fallido (error interno)", job.id)
        job.terminado = timezone.now()
        job.save(update_fields=["estado", "error", "ruta_resultado", "terminado"])
        log.info("job=%s estado=%s duracion=%.2fs", job.id, job.estado, time.monotonic() - inicio)
