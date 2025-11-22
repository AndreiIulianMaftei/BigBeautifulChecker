# --- Stage 1: Build React Frontend ---
FROM node:18 as frontend-builder
WORKDIR /app/website

# Copy dependency files
COPY website/package*.json ./

# Install deps
RUN npm install

# Copy the rest of the frontend code
COPY website/ ./

# Build the static files
RUN npm run build

# --- Stage 2: Build Python Backend ---
FROM python:3.10-slim

WORKDIR /app

# --- FIX: Updated package names for new Debian version ---
RUN apt-get update && apt-get install -y \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*
# -------------------------------------------------------

# 1. Copy requirements from the backend folder
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 2. Copy app.py from the backend folder
COPY backend/app.py .

# 3. Copy the src folder from the backend folder
COPY backend/src/ ./src/

COPY dataset/ /dataset/

# Copy the built React frontend from Stage 1
COPY --from=frontend-builder /app/website/build ./static

# Expose the port
EXPOSE 8000

# Start the app
CMD ["python", "app.py"]