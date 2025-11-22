# ==========================================
# Stage 1: Build the Frontend
# ==========================================
FROM node:18-alpine as frontend-builder

WORKDIR /app/website

# Install deps
COPY website/package*.json ./
RUN npm ci

# Copy source and Build
COPY website/ ./
# NOTE: Check your package.json. If using Vite, this creates 'dist'. If CRA, 'build'.
# We assume 'dist' here based on modern defaults. Change to 'build' if needed.
RUN npm run build


# ==========================================
# Stage 2: Python Backend
# ==========================================
FROM python:3.11-slim

# 1. Install System Dependencies
# libgl1 & libglib2.0-0 are REQUIRED for OpenCV (get_bbox)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 2. Install Python Deps
# We copy requirements first for Docker caching
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# 3. Copy Backend Source Code
COPY backend ./backend

# 4. Copy the Built Frontend from Stage 1
# We place it into 'backend/static' so the modified app.py can find it
# IMPORTANT: Verify if your build folder is 'dist' or 'build'
COPY --from=frontend-builder /app/website/build ./backend/static

# 5. Prepare environment
WORKDIR /app/backend
# Create the temp folders your code uses to prevent permission errors
RUN mkdir -p temp_uploads temp_results

# 6. Start the Server
# Cloud Run injects the PORT environment variable.
# We use shell execution to pass that variable to uvicorn.
CMD sh -c "uvicorn app:app --host 0.0.0.0 --port ${PORT:-8080}"