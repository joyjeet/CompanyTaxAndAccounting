# Multi-stage build: Vite production bundle served by nginx.
#
# Build-time arg:
#   VITE_API_BASE  Absolute URL of the API container app (e.g.
#                  https://ca-ctax-dev-eus-api.bluemoss-1234.eastus2.azurecontainerapps.io)
# Runtime: nginx serves /usr/share/nginx/html on :8080 (ACA-friendly,
# non-root port). All non-asset routes fall through to /index.html so the
# React Router client-side routes keep working on refresh.

# -------- build stage --------
FROM node:20-alpine AS build
WORKDIR /app

ARG VITE_API_BASE=""
ARG VITE_AUTH_MODE=dev
ARG VITE_DEV_DEFAULT_FIRM_ID=""
ARG VITE_DEV_DEFAULT_CLIENT_ID=""

# Install deps first for layer caching.
COPY package.json package-lock.json ./
RUN npm ci

COPY . .

# Bake the API URL into the bundle. Vite inlines VITE_* env at build time.
ENV VITE_API_BASE=${VITE_API_BASE} \
    VITE_AUTH_MODE=${VITE_AUTH_MODE} \
    VITE_DEV_DEFAULT_FIRM_ID=${VITE_DEV_DEFAULT_FIRM_ID} \
    VITE_DEV_DEFAULT_CLIENT_ID=${VITE_DEV_DEFAULT_CLIENT_ID}

RUN npm run build

# -------- runtime stage --------
FROM nginx:1.27-alpine

# Replace the default site with a SPA-friendly one listening on :8080.
RUN rm /etc/nginx/conf.d/default.conf
COPY nginx.conf /etc/nginx/conf.d/default.conf

COPY --from=build /app/dist /usr/share/nginx/html

# nginx:alpine already runs as root in the master process and drops to
# nginx user for workers; keep that default. ACA requires a non-privileged
# port — we listen on 8080.
EXPOSE 8080

# Use foreground mode so the container's PID 1 is nginx.
CMD ["nginx", "-g", "daemon off;"]
