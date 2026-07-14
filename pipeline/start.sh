#!/bin/bash
set -e

echo "Waiting for PostgreSQL to start..."
sleep 5

echo "Initializing database and admin user..."
python -c "
from app import create_app
from app.models import db, User

app = create_app()
with app.app_context():
    db.create_all()
    if not User.query.filter_by(username='admin').first():
        admin = User(username='admin', role='admin')
        admin.set_password('admin123')
        db.session.add(admin)
        db.session.commit()
        print('Admin user created (admin / admin123)')
    else:
        print('Admin user already exists.')
"

echo "Starting Gunicorn..."
exec gunicorn --bind 0.0.0.0:8080 --workers 2 run:app
