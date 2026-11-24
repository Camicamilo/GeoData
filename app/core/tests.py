"""Pruebas reproducibles:  docker compose exec web python manage.py test core"""
import shutil
import tempfile
from pathlib import Path

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings

from .models import Estado, EventoAuditoria, Job, Perfil
from .permisos import PERMISOS, puede

CSV_OK = b"muestra_id,ph,humedad,nitrogeno,fosforo\nM1,6.5,30,120,15\nM2,7.1,45,90,22\n"
CSV_MAL = b"id,acidez\n1,2\n"
PASS = "ClaveDePrueba-2026"

TMP = tempfile.mkdtemp()


@override_settings(MEDIA_ROOT=TMP, WORKER_DEMORA_SECONDS=0, COOKIES_SECURE=False,
                   SESSION_COOKIE_SECURE=False, CSRF_COOKIE_SECURE=False)
class Base(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TMP, ignore_errors=True)

    def crear(self, nombre, rol):
        u = User.objects.create_user(nombre, password=PASS)
        Perfil.objects.create(user=u, rol=rol)
        return u

    def setUp(self):
        self.ana = self.crear("ana", "usuario")
        self.beto = self.crear("beto", "usuario")
        self.op = self.crear("op", "operador")
        self.adm = self.crear("adm", "admin")

    def login(self, user):
        self.client.force_login(user)

    def subir(self, contenido=CSV_OK, nombre="m.csv"):
        return self.client.post("/jobs/nuevo", {"archivo": SimpleUploadedFile(nombre, contenido)})

    def procesar_cola(self):
        from .management.commands.worker import Command

        w = Command()
        w.nombre = "test"
        while (job := w.tomar_trabajo()) is not None:
            w.ejecutar(job)


class AutenticacionTests(Base):
    def test_contrasena_con_hash(self):
        self.assertTrue(self.ana.password.startswith("pbkdf2_sha256$"))
        self.assertNotIn(PASS, self.ana.password)

    def test_sin_sesion_redirige_a_login(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 302)
        self.assertIn("/accounts/login/", r["Location"])

    def test_login_fallido_auditado(self):
        self.client.post("/accounts/login/", {"username": "ana", "password": "mala"})
        self.assertTrue(EventoAuditoria.objects.filter(accion="LOGIN_FALLIDO", username="ana").exists())


class AutorizacionTests(Base):
    def test_tres_roles_diferenciados(self):
        conjuntos = {r: {a for a, roles in PERMISOS.items() if r in roles} for r in ("usuario", "operador", "admin")}
        self.assertLess(conjuntos["usuario"], conjuntos["operador"])
        self.assertLess(conjuntos["operador"], conjuntos["admin"])

    def test_usuario_no_entra_a_gestion(self):  # reto 1
        self.login(self.ana)
        self.assertEqual(self.client.get("/gestion/usuarios/").status_code, 403)
        self.assertEqual(self.client.get("/gestion/auditoria/").status_code, 403)
        self.assertTrue(EventoAuditoria.objects.filter(username="ana", accion="ACCESO_DENEGADO").exists())

    def test_operador_ve_todos_usuario_no(self):  # reto 2
        self.login(self.op)
        self.assertEqual(self.client.get("/trabajos/").status_code, 200)
        self.login(self.ana)
        self.assertEqual(self.client.get("/trabajos/").status_code, 403)

    def test_admin_gestiona(self):
        self.login(self.adm)
        self.assertEqual(self.client.get("/gestion/usuarios/").status_code, 200)
        self.client.post("/gestion/usuarios/nuevo", {"username": "nuevo", "password": PASS, "rol": "operador"})
        self.assertTrue(puede(User.objects.get(username="nuevo"), "ver_todos"))


class AislamientoTests(Base):  # reto 3
    def setUp(self):
        super().setUp()
        self.login(self.ana)
        self.subir()
        self.job_ana = Job.objects.get(owner=self.ana)
        self.procesar_cola()

    def test_otro_usuario_no_ve_ni_descarga(self):
        self.login(self.beto)
        for url in (f"/jobs/{self.job_ana.id}/", f"/jobs/{self.job_ana.id}/descargar",
                    f"/jobs/{self.job_ana.id}/estado.json"):
            self.assertEqual(self.client.get(url).status_code, 404, url)
        self.assertEqual(EventoAuditoria.objects.filter(username="beto", accion="ACCESO_DENEGADO").count(), 3)

    def test_operador_ve_estado_pero_no_descarga_ajeno(self):
        self.login(self.op)
        self.assertEqual(self.client.get(f"/jobs/{self.job_ana.id}/").status_code, 200)
        self.assertEqual(self.client.get(f"/jobs/{self.job_ana.id}/descargar").status_code, 404)

    def test_duena_descarga(self):
        r = self.client.get(f"/jobs/{self.job_ana.id}/descargar")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(EventoAuditoria.objects.filter(username="ana", accion="DESCARGA").exists())

    def test_archivos_separados_por_usuario(self):
        self.assertIn(f"/{self.ana.id}/originales/", self.job_ana.ruta_original)


class ProcesamientoTests(Base):
    def setUp(self):
        super().setUp()
        self.login(self.ana)

    def test_ciclo_completo(self):
        r = self.subir()
        self.assertEqual(r.status_code, 302)
        job = Job.objects.get()
        self.assertEqual(job.estado, Estado.PENDIENTE)  # la petición no procesa: es asíncrono
        self.procesar_cola()
        job.refresh_from_db()
        self.assertEqual(job.estado, Estado.COMPLETADO)
        self.assertTrue(Path(job.ruta_resultado).exists())

    def test_contenido_invalido_queda_fallido(self):
        self.subir(CSV_MAL)
        self.procesar_cola()
        job = Job.objects.get()
        self.assertEqual(job.estado, Estado.FALLIDO)
        self.assertIn("Encabezado", job.error)

    def test_rechazos_de_entrada(self):
        self.assertEqual(self.subir(b"%PDF-1.4\x00\xff\xfe", "x.csv").status_code, 400)
        self.assertEqual(self.subir(CSV_OK, "x.exe").status_code, 400)
        with self.settings(MAX_UPLOAD_BYTES=10):
            self.assertEqual(self.subir().status_code, 400)
        self.assertEqual(Job.objects.count(), 0)
        self.assertEqual(EventoAuditoria.objects.filter(accion="RECHAZO_ARCHIVO").count(), 3)

    def test_cuota_regla_de_negocio(self):
        for _ in range(3):
            self.assertEqual(self.subir().status_code, 302)
        self.assertEqual(self.subir().status_code, 429)
        self.assertTrue(EventoAuditoria.objects.filter(accion="CUOTA_EXCEDIDA").exists())
        self.procesar_cola()
        self.assertEqual(self.subir().status_code, 302)  # al terminar, se libera la cuota

    def test_reintento_por_operador(self):
        self.subir(CSV_MAL)
        self.procesar_cola()
        job = Job.objects.get()
        self.assertEqual(self.client.post(f"/jobs/{job.id}/reintentar").status_code, 403)  # usuario no
        self.login(self.op)
        self.client.post(f"/jobs/{job.id}/reintentar")
        job.refresh_from_db()
        self.assertEqual(job.estado, Estado.PENDIENTE)

    def test_recupera_huerfanos(self):
        from datetime import timedelta

        from django.utils import timezone

        from .management.commands.worker import Command

        self.subir()
        Job.objects.update(estado=Estado.EN_EJECUCION, iniciado=timezone.now() - timedelta(hours=1))
        Command().recuperar_huerfanos()
        self.assertEqual(Job.objects.get().estado, Estado.PENDIENTE)


class ConsolaTests(Base):
    def test_seed_demo(self):
        import os

        os.environ["DEMO_PASSWORD"] = PASS
        call_command("seed_demo", verbosity=0)
        self.assertEqual(User.objects.get(username="jefe").perfil.rol, "admin")
