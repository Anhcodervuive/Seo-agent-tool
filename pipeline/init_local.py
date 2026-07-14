
from app import create_app
from app.models import db, User

app = create_app()
with app.app_context():
    print("Creating tables...")
    db.create_all()
    
    admin = User.query.filter_by(username='admin').first()
    if not admin:
        print("Creating admin user...")
        admin = User(username='admin', role='admin')
        admin.set_password('admin123')
        db.session.add(admin)
        db.session.commit()
        print("Admin user created (admin / admin123)!")
    else:
        print("Admin user already exists.")
