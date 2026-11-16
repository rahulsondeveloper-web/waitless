# Builds the Angular app and serves it with Nginx (which also proxies /api, /socket.io, /media).
#   docker build -f infra/docker/frontend.Dockerfile -t waitless-web .
FROM node:24-alpine AS build
WORKDIR /src
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ .
RUN npx ng build --configuration production

FROM nginx:1.27-alpine
COPY infra/nginx/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /src/dist/frontend/browser /usr/share/nginx/html
EXPOSE 80
