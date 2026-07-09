from flask import Flask
from flask_migrate import Migrate
import config
from models import db, User, Client, UserClient, AISetting, Snapshot, CrawlIssue, Ga4Metric, GscMetric, Ranking, BacklinkHistory, Keyword, Competitor

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = config.SQLALCHEMY_DATABASE_URI
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)
migrate = Migrate(app, db)

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        print("Database tables created successfully!")
