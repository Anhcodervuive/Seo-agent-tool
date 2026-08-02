#!/bin/bash
set -e

echo "Waiting for PostgreSQL to start..."
sleep 5

echo "Applying database migrations..."
python -m flask --app manage.py db upgrade

echo "Ensuring admin user exists..."
python -c "
from app import create_app
from app.models import User, db
import os

app = create_app()
with app.app_context():
    admin_username = os.environ.get('ADMIN_USERNAME', 'admin')
    admin_password = os.environ.get('ADMIN_PASSWORD', 'admin123')
    if not User.query.filter_by(username=admin_username).first():
        admin = User(username=admin_username, role='admin')
        admin.set_password(admin_password)
        db.session.add(admin)
        db.session.commit()
        print(f'Admin user created ({admin_username})')
    else:
        print('Admin user already exists.')
"

echo "Starting Gunicorn..."
exec gunicorn --bind 0.0.0.0:8080 --workers 2 run:app
