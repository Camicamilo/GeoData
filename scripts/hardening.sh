#!/usr/bin/env bash
# Preparación y endurecimiento del servidor (EC2 Ubuntu 24.04). Ejecutar UNA vez como el usuario
# 'ubuntu' de la AMI:   sudo bash scripts/hardening.sh
set -euo pipefail
[ "$(id -u)" -eq 0 ] || { echo "Ejecutar con sudo"; exit 1; }

echo "== 1. Actualizaciones y actualizaciones automáticas de seguridad"
apt-get update -y
DEBIAN_FRONTEND=noninteractive apt-get upgrade -y
DEBIAN_FRONTEND=noninteractive apt-get install -y unattended-upgrades docker.io docker-compose-v2 git
dpkg-reconfigure -f noninteractive unattended-upgrades
systemctl enable --now unattended-upgrades docker

echo "== 2. Usuario no privilegiado 'deploy' para operar la aplicación (sin sudo)"
id deploy >/dev/null 2>&1 || useradd --create-home --shell /bin/bash deploy
usermod -aG docker deploy   # OJO: el grupo docker equivale a root -> documentado en Limitaciones
install -d -m 700 -o deploy -g deploy /home/deploy/.ssh
if [ -f /home/ubuntu/.ssh/authorized_keys ]; then
  install -m 600 -o deploy -g deploy /home/ubuntu/.ssh/authorized_keys /home/deploy/.ssh/authorized_keys
fi

echo "== 3. Directorio de la aplicación: dueño deploy, sin acceso para otros"
install -d -m 750 -o deploy -g deploy /opt/agrolab

echo "== 4. SSH: solo llave, sin root, sin contraseñas"
cat > /etc/ssh/sshd_config.d/90-agrolab.conf <<'EOF'
PermitRootLogin no
PasswordAuthentication no
KbdInteractiveAuthentication no
PubkeyAuthentication yes
MaxAuthTries 3
X11Forwarding no
AllowUsers ubuntu deploy
EOF
chmod 600 /etc/ssh/sshd_config.d/90-agrolab.conf
sshd -t && systemctl reload ssh

echo "== 5. Servicios que no se usan"
for s in snapd.service snapd.socket ModemManager.service; do
  systemctl disable --now "$s" 2>/dev/null && echo "deshabilitado $s" || true
done

echo
echo "Listo. Siguientes pasos (como deploy):"
echo "  sudo -iu deploy"
echo "  git clone <repo> /opt/agrolab && cd /opt/agrolab"
echo "  cp .env.example .env && chmod 600 .env && nano .env"
echo "  docker compose up -d --build"
