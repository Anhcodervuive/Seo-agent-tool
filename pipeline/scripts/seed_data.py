from app import create_app
from app.models import db, Client, Keyword, Snapshot

app = create_app()

def seed():
    with app.app_context():
        # Clear existing data to avoid duplicates
        Client.query.delete()
        from app.models import Keyword, Competitor, Snapshot, User
        Keyword.query.delete()
        Snapshot.query.delete()
        Competitor.query.delete()

        print("Seeding old clients data...")

        c1 = Client(
            name='Hire Programmer',
            domain='hireprogrammer.com',
            business_context='Freelance platform for hiring developers.',
            location='United States',
            ga4_property_id='310000000',
            gsc_site_url='https://hireprogrammer.com',
            crawl_mode='full'
        )
        
        c2 = Client(
            name='Infozzle',
            domain='infozzle.com',
            business_context='Digital marketing and IT services.',
            location='United States',
            ga4_property_id='410000000',
            gsc_site_url='https://infozzle.com',
            crawl_mode='full'
        )

        db.session.add_all([c1, c2])
        db.session.flush()

        print(f"Created Clients: {c1.name}, {c2.name}")

        # Assign to admin user if exists
        admin = User.query.filter_by(username='admin').first()
        if admin:
            admin.clients.extend([c1, c2])
            print("Assigned clients to admin user.")

        # Add some tracked keywords
        k1 = Keyword(client_id=c1.id, keyword='hire programmer', priority='high')
        k2 = Keyword(client_id=c1.id, keyword='hire python developer', priority='high')
        k3 = Keyword(client_id=c2.id, keyword='it services', priority='high')
        k4 = Keyword(client_id=c2.id, keyword='tech news', priority='high')
        
        db.session.add_all([k1, k2, k3, k4])
        
        # Add Competitors
        comp1 = Competitor(client_id=c1.id, domain='upwork.com')
        comp2 = Competitor(client_id=c2.id, domain='theverge.com')
        db.session.add_all([comp1, comp2])
        
        # Add a dummy snapshot to show "runs" in dashboard
        s1 = Snapshot(client_id=c1.id, status='complete', notes='Migrated from old DB')
        s2 = Snapshot(client_id=c2.id, status='complete', notes='Migrated from old DB')

        db.session.add_all([s1, s2])
        db.session.commit()

        print("Seed complete! Data synchronized successfully.")

if __name__ == '__main__':
    seed()
