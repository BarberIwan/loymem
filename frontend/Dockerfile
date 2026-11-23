FROM node:22-slim AS build
WORKDIR /app
RUN corepack enable
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY . .
ARG LOYMEM_API_URL=http://api:8000
ENV LOYMEM_API_URL=$LOYMEM_API_URL NEXT_TELEMETRY_DISABLED=1
RUN pnpm run build

FROM node:22-slim
WORKDIR /app
RUN corepack enable
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1
COPY --from=build /app ./
USER node
EXPOSE 3000
CMD ["pnpm", "start"]
