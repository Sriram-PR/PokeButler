# Use lightweight Python image
FROM python:3.12-slim

# Keep Python from buffering stdout and stderr (useful for logs)
ENV PYTHONUNBUFFERED=1
# Prevent Python from writing pyc files to disc
ENV PYTHONDONTWRITEBYTECODE=1

# Create a non-root user to run the app
# Security Best Practice: Don't run apps as root
RUN useradd -m -u 1000 botuser

# Set working directory
WORKDIR /app

# Install dependencies
# Done before copying code to leverage Docker Layer Caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY . .

# Setup Data Directory with correct permissions
# We create the directory and assign ownership to the non-root user
RUN mkdir -p data && chown -R botuser:botuser /app

# Switch to non-root user
USER botuser

# Define the volume for persistence
# This tells Docker/Railway that this folder holds persistent data
VOLUME ["/app/data"]

# Run the bot
CMD ["python", "bot.py"]