# Imagen oficial de nginx que corre SIN root (usuario nginx, UID 101) y escucha en 8080/8443
FROM nginxinc/nginx-unprivileged:1.27-alpine

USER root
RUN apk add --no-cache openssl \
 && mkdir -p /etc/nginx/certs \
 && chown 101:101 /etc/nginx/certs \
 && chmod 700 /etc/nginx/certs
COPY default.conf /etc/nginx/conf.d/default.conf
COPY proxy_params.inc /etc/nginx/conf.d/proxy_params.inc
COPY 10-certificado.sh /docker-entrypoint.d/10-certificado.sh
RUN chmod 755 /docker-entrypoint.d/10-certificado.sh
USER 101
