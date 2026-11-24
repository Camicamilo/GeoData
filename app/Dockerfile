FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    MEDIA_ROOT=/data/media

# Usuario NO privilegiado para ejecutar la app (UID fijo 1000, sin shell)
RUN groupadd --gid 1000 app \
 && useradd --uid 1000 --gid app --no-create-home --shell /usr/sbin/nologin app

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

# El código queda de root y solo lectura para 'app': si comprometen la app, no puede modificarse a sí misma
COPY . .
RUN chmod -R a-w /app \
 && mkdir -p /data/media \
 && chown app:app /data/media \
 && chmod 750 /data/media

USER app
EXPOSE 8000
ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["web"]
