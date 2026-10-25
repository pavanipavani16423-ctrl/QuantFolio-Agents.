FROM node:24-alpine AS build
WORKDIR /web
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
ARG NEXT_PUBLIC_API_URL=http://localhost:8000
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
RUN npm run build

FROM node:24-alpine
WORKDIR /web
ENV NODE_ENV=production
COPY --from=build /web/.next ./.next
COPY --from=build /web/public ./public
COPY --from=build /web/node_modules ./node_modules
COPY --from=build /web/package.json ./package.json
EXPOSE 3000
CMD ["npm", "run", "start"]
