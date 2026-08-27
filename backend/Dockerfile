FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# libgomp1 is required by XGBoost's OpenMP runtime.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY . /app

# Baked into the image so the container has the admin's CSS without needing a
# writable volume or a build step at boot. USE_SQLITE keeps this from wanting a
# database: collectstatic touches no data, but Django still builds settings.
RUN USE_SQLITE=1 DJANGO_SECRET_KEY=build-only python manage.py collectstatic --noinput

EXPOSE 8000

# Gunicorn, not `runserver`. The development server is single-threaded and
# explicitly not built to face the internet - Django itself says so on boot.
#
# docker-compose overrides this with runserver for local work, where the
# autoreloader is the entire point. This CMD is what a deployed container runs.
#
# Two workers with two threads each fits a small instance. The detection run is
# CPU-bound and synchronous, so the timeout is generous: scoring a large network
# genuinely takes tens of seconds, and killing it mid-run would look like a bug.
CMD ["gunicorn", "config.wsgi:application", \
     "--bind", "0.0.0.0:8000", \
     "--workers", "2", \
     "--threads", "2", \
     "--timeout", "120", \
     "--access-logfile", "-", \
     "--error-logfile", "-"]
