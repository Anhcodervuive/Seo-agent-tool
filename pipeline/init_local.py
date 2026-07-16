from app import create_app
from app.models import db, User
import os

app = create_app()
with app.app_context():
    print("Creating tables...")
    db.create_all()
    
    admin_username = os.environ.get('ADMIN_USERNAME', 'admin')
    admin_password = os.environ.get('ADMIN_PASSWORD', 'admin123')
    admin = User.query.filter_by(username=admin_username).first()
    if not admin:
        print("Creating admin user...")
        admin = User(username=admin_username, role='admin')
        admin.set_password(admin_password)
        db.session.add(admin)
        db.session.commit()
        print(f"Admin user created ({admin_username})!")
    else:
        print("Admin user already exists.")
