#!/bin/sh
set -e
umask 027   # archivos nuevos: 640 / directorios: 750

case "$1" in
  web)
    python manage.py migrate --noinput
    exec gunicorn agrolab.wsgi:application \
      --bind 0.0.0.0:8000 --workers "${GUNICORN_WORKERS:-3}" \
      --access-logfile - --error-logfile - --worker-tmp-dir /tmp
    ;;
  worker)
    exec python manage.py worker
    ;;
  *)
    exec "$@"
    ;;
esac
