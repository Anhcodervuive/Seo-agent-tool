from app import create_app
from flask_migrate import Migrate
from app.models import db, User, Client, UserClient, AISetting, Snapshot, CrawlIssue, Ga4Metric, GscMetric, Ranking, BacklinkHistory, Keyword, Competitor

app = create_app()
migrate = Migrate(app, db)

if __name__ == '__main__':
    app.run()
