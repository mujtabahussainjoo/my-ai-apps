# Production image for the my-exam Next.js app.
#
# The app needs PostgreSQL at runtime. The compose file starts Postgres and
# this container applies the idempotent schema before `next start`.

FROM node:20-alpine AS builder

WORKDIR /app

ENV NEXT_TELEMETRY_DISABLED=1 \
    DATABASE_URL=postgres://myexam:myexam@postgres:5432/myexam \
    SESSION_SECRET=ci-build-session-secret

COPY package.json package-lock.json ./
RUN npm ci --ignore-scripts

COPY . .
RUN node scripts/patch-react-perf.mjs
ENV NODE_ENV=production
RUN npm run build


FROM node:20-alpine AS runner

WORKDIR /app

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0

COPY --from=builder /app ./
RUN chmod +x docker-entrypoint.sh

EXPOSE 3000

ENTRYPOINT ["./docker-entrypoint.sh"]
