#!/usr/bin/env bash
# Muestra en un solo paso las evidencias del checklist del docente.
#   bash scripts/evidencias.sh            (desde /opt/agrolab)
#   bash scripts/evidencias.sh > evidencias_$(date +%F).txt
cd "$(dirname "$0")/.."
t() { echo; echo "================ $* ================"; }

t "Entorno: SO y nube"
uname -a; grep PRETTY_NAME /etc/os-release
curl -s -m 2 http://169.254.169.254/latest/meta-data/instance-type 2>/dev/null && echo " (instancia EC2)" || echo "(metadatos EC2 no disponibles)"

t "Contenedores activos y su función"
docker compose ps

t "Recursos: CPU, memoria (con LÍMITE) y disco"
docker stats --no-stream --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.MemPerc}}"
free -h; df -h /

t "Límites aplicados al worker (NanoCpus=500000000 -> 0.5 CPU; Memory en bytes)"
docker inspect "$(docker compose ps -q worker | head -1)" \
  --format 'cpus={{.HostConfig.NanoCpus}} memoria={{.HostConfig.Memory}} readonly={{.HostConfig.ReadonlyRootfs}} capdrop={{.HostConfig.CapDrop}} secopt={{.HostConfig.SecurityOpt}}'

t "Hardening: usuario dentro de cada contenedor (no root)"
for s in web worker nginx; do printf "%-7s " "$s"; docker compose exec -T "$s" id; done
printf "%-7s " db; docker compose exec -T db sh -c 'ps -o user,comm | grep postgres | head -2 | tr "\n" " "'; echo

t "Red: puertos escuchando en el host (solo 22, 80, 443)"
sudo ss -tlnp | grep -E 'LISTEN' || ss -tln

t "Red: la base de datos NO publica puertos"
docker compose port db 5432 2>&1 || true

t "Permisos de configuración y datos"
ls -l .env
ls -ld /opt/agrolab 2>/dev/null || true
docker compose exec -T web sh -c 'ls -ld /data/media /data/media/* 2>/dev/null | head; echo; touch /app/x 2>&1 | head -1'

t "SSH endurecido"
sudo sshd -T 2>/dev/null | grep -Ei '^(permitrootlogin|passwordauthentication|maxauthtries)' || echo "(requiere sudo)"

t "Actualizaciones automáticas"
systemctl is-active unattended-upgrades 2>/dev/null || echo "no instalado"

t "Repositorio sin secretos"
git ls-files | grep -E '(^|/)\.env$|\.key$|\.pem$' && echo "¡HAY SECRETOS VERSIONADOS!" || echo "OK: .env y llaves no están versionados"

t "Auditoría: últimos 10 eventos"
docker compose exec -T db psql -U "$(grep ^POSTGRES_USER .env | cut -d= -f2)" -d "$(grep ^POSTGRES_DB .env | cut -d= -f2)" \
  -c "SELECT to_char(fecha,'YYYY-MM-DD HH24:MI:SS') fecha, username, accion, resultado, objeto FROM core_eventoauditoria ORDER BY fecha DESC LIMIT 10;"

t "Últimas líneas del worker"
docker compose logs --tail 10 worker
