#!/bin/sh
# Renders the Nginx config, using the Let's Encrypt certificate when it exists and a temporary self-signed one
# until then (so Nginx can start and answer the ACME challenge). Re-checks every 6 hours and reloads, which also
# picks up renewed certificates.
set -eu

: "${DOMAIN:?DOMAIN is required}"
: "${MEDIA_HOST:=}"
LE_DIR="/etc/letsencrypt/live/${DOMAIN}"
SELF_DIR="/etc/nginx/selfsigned"
mkdir -p /etc/nginx/snippets /var/www/acme

render() {
  if [ -f "${LE_DIR}/fullchain.pem" ]; then
    SSL_CERT="${LE_DIR}/fullchain.pem"
    SSL_KEY="${LE_DIR}/privkey.pem"
  else
    if [ ! -f "${SELF_DIR}/cert.pem" ]; then
      mkdir -p "${SELF_DIR}"
      openssl req -x509 -nodes -newkey rsa:2048 -days 7 -subj "/CN=${DOMAIN}" \
        -keyout "${SELF_DIR}/key.pem" -out "${SELF_DIR}/cert.pem" >/dev/null 2>&1
    fi
    SSL_CERT="${SELF_DIR}/cert.pem"
    SSL_KEY="${SELF_DIR}/key.pem"
  fi
  export DOMAIN MEDIA_HOST SSL_CERT SSL_KEY
  vars='${DOMAIN} ${MEDIA_HOST} ${SSL_CERT} ${SSL_KEY}'
  envsubst "$vars" < /etc/nginx/templates-waitless/default.conf.template > /etc/nginx/conf.d/default.conf
  envsubst "$vars" < /etc/nginx/templates-waitless/security-headers.conf.template > /etc/nginx/snippets/security-headers.conf
}

render
( while :; do sleep 6h; render; nginx -s reload; done ) &
exec nginx -g 'daemon off;'
