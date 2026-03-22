# =============================================================================
# Frontend Dockerfile - Next.js 15 + Node 22
# =============================================================================
# Build:  docker build -t trading-frontend ./frontend
# Run:    docker run -p 3000:3000 trading-frontend
# =============================================================================

FROM node:22-alpine AS base

# Enable corepack for modern package manager support
RUN corepack enable

WORKDIR /app

# Copy dependency manifests first (layer caching)
COPY package.json ./
COPY tsconfig.json ./
COPY next.config.ts ./
COPY postcss.config.mjs ./

# Install dependencies
RUN npm install

# Copy application source
COPY src/ ./src/
COPY public/ ./public/

# Expose the Next.js dev server port
EXPOSE 3000

# Run Next.js development server
# Bind to 0.0.0.0 so it's accessible outside the container
CMD ["npm", "run", "dev", "--", "--hostname", "0.0.0.0"]
