FROM node:22-alpine AS build
WORKDIR /app

ARG VITE_API_BASE=http://localhost:8000
ARG VITE_WS_URL=ws://localhost:8000/ws/live
ARG VITE_MAPBOX_TOKEN=
ENV VITE_API_BASE=$VITE_API_BASE VITE_WS_URL=$VITE_WS_URL VITE_MAPBOX_TOKEN=$VITE_MAPBOX_TOKEN

COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
# Single-page app: unknown paths fall through to index.html so /alerts and
# /moderation survive a hard refresh.
RUN printf 'server {\n\
  listen 80;\n\
  root /usr/share/nginx/html;\n\
  location / { try_files $uri $uri/ /index.html; }\n\
}\n' > /etc/nginx/conf.d/default.conf
EXPOSE 80
