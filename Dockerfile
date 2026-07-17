# Munshi — hosted/cloud tenant image. This is a SEPARATE deployment target
# from the desktop installer (build/munshi.spec) — see
# C:\Users\adity\.claude\plans\jaunty-wobbling-swing.md for the full plan.
# One container = one tenant, with its own persistent volume mounted at /data.
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Code only — bills.db/uploads/backups/.flask_secret live on the mounted
# volume at /data (MUNSHI_APP_DIR below), never baked into the image, so a
# redeploy never touches tenant data.
COPY app.py .
COPY munshi/ munshi/
COPY templates/ templates/
COPY static/ static/
COPY translations/ translations/
COPY data/ data/

ENV HOST=0.0.0.0
ENV PORT=8080
ENV MUNSHI_APP_DIR=/data
ENV MUNSHI_HTTPS=1
ENV MUNSHI_BEHIND_PROXY=1
ENV MUNSHI_HEADLESS=1

EXPOSE 8080
CMD ["python", "app.py"]
