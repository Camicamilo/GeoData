#!/bin/sh
# Genera un certificado autofirmado la primera vez (queda en el volumen 'certs', no en el repo).
set -e
C=/etc/nginx/certs
if [ ! -f "$C/servidor.crt" ]; then
  echo "Generando certificado autofirmado para ${TLS_CN:-agrolab.local}"
  openssl req -x509 -nodes -newkey rsa:2048 -days 365 \
    -keyout "$C/servidor.key" -out "$C/servidor.crt" \
    -subj "/CN=${TLS_CN:-agrolab.local}/O=AgroLab Sugamuxi (ficticio)" >/dev/null 2>&1
  chmod 600 "$C/servidor.key"
fi
