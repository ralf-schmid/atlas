FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

FROM node:22-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

FROM node:22-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
# CVE-2026-111497 (Brotli decoder RCE): refuse to build on an unpatched Node 22 (< 22.23.4)
RUN node -e 'const [a,b,c]=process.versions.node.split(".").map(Number);process.exit(a>22||(a===22&&(b>23||(b===23&&c>=4)))?0:1)' \
    || (echo "Node $(node -v) is vulnerable to CVE-2026-111497, need >= 22.23.4" && exit 1)
COPY --from=builder /app/public ./public
COPY --from=builder /app/.next ./.next
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/package.json ./package.json

EXPOSE 3000
CMD ["npm", "start"]
