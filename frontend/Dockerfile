FROM node:20-alpine AS build

WORKDIR /app

ARG VITE_API_BASE=/api
ENV VITE_API_BASE=${VITE_API_BASE}

COPY package.json package-lock.json* ./
RUN npm ci

COPY . .
RUN npm run build

# Production stage - serve with nginx
FROM nginx:alpine

RUN apk add --no-cache ca-certificates
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/templates/default.conf.template
ENV PORT=80
ENV BACKEND_UPSTREAM=http://backend:8000

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
