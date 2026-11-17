# Builds the Angular app and serves it with Nginx (TLS, security headers, /api, /socket.io, /media proxy).
#   docker build -f infra/docker/frontend.Dockerfile -t waitless-web .
FROM node:24-alpine AS build
WORKDIR /src
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ .
RUN npx ng build --configuration production

FROM nginx:1.27-alpine
RUN apk add --no-cache openssl \
    && rm -f /etc/nginx/conf.d/default.conf
COPY infra/nginx/default.conf.template infra/nginx/security-headers.conf.template /etc/nginx/templates-waitless/
COPY infra/nginx/proxy-params.conf /etc/nginx/snippets/proxy-params.conf
COPY infra/nginx/entrypoint.sh /entrypoint-waitless.sh
COPY --from=build /src/dist/frontend/browser /usr/share/nginx/html
RUN chmod +x /entrypoint-waitless.sh
EXPOSE 80 443
HEALTHCHECK --interval=30s --timeout=5s CMD wget -q --spider --no-check-certificate https://127.0.0.1/ || exit 1
ENTRYPOINT ["/entrypoint-waitless.sh"]
