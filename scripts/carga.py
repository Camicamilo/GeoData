#!/usr/bin/env python3
"""Prueba de carga: N usuarios suben J trabajos cada uno y se mide hasta que todos terminan.

Solo biblioteca estándar. El certificado es autofirmado, por eso --inseguro.

    python3 scripts/carga.py --url https://IP --inseguro --usuarios 10 --trabajos 3 \
        --archivo dataset/muestras_valle_completo.csv --password "$DEMO_PASSWORD"

En otra terminal, mientras corre:   docker stats
Repetir con varios workers:         docker compose up -d --scale worker=3
"""
import argparse
import http.cookiejar
import json
import re
import ssl
import sys
import threading
import time
import urllib.parse
import urllib.request
import uuid


class Cliente:
    def __init__(self, base, contexto):
        self.base = base.rstrip("/")
        self.cookies = http.cookiejar.CookieJar()
        self.op = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.cookies), urllib.request.HTTPSHandler(context=contexto))

    def csrf(self):
        return next((c.value for c in self.cookies if c.name == "csrftoken"), "")

    def req(self, metodo, ruta, datos=None, tipo=None):
        r = urllib.request.Request(self.base + ruta, data=datos, method=metodo)
        r.add_header("Referer", self.base + "/")
        if tipo:
            r.add_header("Content-Type", tipo)
        if metodo == "POST":
            r.add_header("X-CSRFToken", self.csrf())
        try:
            with self.op.open(r, timeout=30) as resp:
                return resp.status, resp.geturl(), resp.read()
        except urllib.error.HTTPError as e:
            return e.code, ruta, e.read()

    def login(self, usuario, password):
        self.req("GET", "/accounts/login/")
        datos = urllib.parse.urlencode({"username": usuario, "password": password,
                                        "csrfmiddlewaretoken": self.csrf()}).encode()
        _, url, _ = self.req("POST", "/accounts/login/", datos, "application/x-www-form-urlencoded")
        if "/accounts/login/" in url:
            raise SystemExit(f"Login fallido para {usuario}")

    def subir(self, nombre, contenido):
        limite = uuid.uuid4().hex
        cuerpo = (f"--{limite}\r\nContent-Disposition: form-data; name=\"csrfmiddlewaretoken\"\r\n\r\n{self.csrf()}\r\n"
                  f"--{limite}\r\nContent-Disposition: form-data; name=\"archivo\"; filename=\"{nombre}\"\r\n"
                  f"Content-Type: text/csv\r\n\r\n").encode() + contenido + f"\r\n--{limite}--\r\n".encode()
        estado, url, _ = self.req("POST", "/jobs/nuevo", cuerpo, f"multipart/form-data; boundary={limite}")
        m = re.search(r"/jobs/([0-9a-f-]{36})/", url)
        return estado, (m.group(1) if m else None)

    def estado(self, job_id):
        _, _, cuerpo = self.req("GET", f"/jobs/{job_id}/estado.json")
        return json.loads(cuerpo)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--url", default="https://localhost")
    p.add_argument("--inseguro", action="store_true", help="aceptar certificado autofirmado")
    p.add_argument("--usuarios", type=int, default=10)
    p.add_argument("--trabajos", type=int, default=3)
    p.add_argument("--archivo", default="dataset/muestras_valle_completo.csv")
    p.add_argument("--password", required=True)
    a = p.parse_args()

    ctx = ssl.create_default_context()
    if a.inseguro:
        ctx.check_hostname, ctx.verify_mode = False, ssl.CERT_NONE
    contenido = open(a.archivo, "rb").read()

    clientes = []
    for i in range(1, a.usuarios + 1):
        c = Cliente(a.url, ctx)
        c.login(f"tecnico{i}", a.password)
        clientes.append(c)

    print(f"Carga: {a.usuarios} usuarios x {a.trabajos} trabajos = {a.usuarios * a.trabajos} "
          f"trabajos de {len(contenido):,} B")
    jobs, rechazos, lock = [], 0, threading.Lock()
    t0 = time.monotonic()

    def enviar(c):
        nonlocal rechazos
        for _ in range(a.trabajos):
            estado, jid = c.subir("carga.csv", contenido)
            with lock:
                if jid:
                    jobs.append((c, jid))
                else:
                    rechazos += 1

    hilos = [threading.Thread(target=enviar, args=(c,)) for c in clientes]
    [h.start() for h in hilos]
    [h.join() for h in hilos]
    t_envio = time.monotonic() - t0
    print(f"Envío: {len(jobs)} aceptados, {rechazos} rechazados en {t_envio:.2f} s")

    pendientes, duraciones, estados = dict((jid, c) for c, jid in jobs), [], {}
    while pendientes:
        for jid, c in list(pendientes.items()):
            e = c.estado(jid)
            if e["estado"] in ("completado", "fallido"):
                estados[e["estado"]] = estados.get(e["estado"], 0) + 1
                if e["duracion"]:
                    duraciones.append(e["duracion"])
                del pendientes[jid]
        time.sleep(0.5)
    total = time.monotonic() - t0

    print(f"Resultado: {estados}")
    print(f"Tiempo total: {total:.2f} s  |  throughput: {len(jobs) / total:.2f} trabajos/s")
    if duraciones:
        print(f"Duración por trabajo (worker): media {sum(duraciones) / len(duraciones):.2f} s, "
              f"máx {max(duraciones):.2f} s")


if __name__ == "__main__":
    sys.exit(main())
