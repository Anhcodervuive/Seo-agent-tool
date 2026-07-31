FROM python:3.11-slim

# Install system dependencies for PostgreSQL and WeasyPrint PDF rendering.
# WeasyPrint needs cairo/pango/gdk-pixbuf/fontconfig style native libraries.
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    libcairo2 \
    libgdk-pixbuf-2.0-0 \
    libffi8 \
    libfontconfig1 \
    libglib2.0-0 \
    libpango-1.0-0 \
    libpangoft2-1.0-0 \
    shared-mime-info \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Ensure start script is executable
RUN chmod +x start.sh

# Expose port
EXPOSE 8080

# Run the start script
CMD ["./start.sh"]
