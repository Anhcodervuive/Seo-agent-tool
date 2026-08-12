from app import create_app
from flask_migrate import Migrate
from app.models import (
    AISetting,
    BacklinkAnchor,
    BacklinkHistory,
    BacklinkItem,
    BacklinkReferringDomain,
    Client,
    Competitor,
    CrawlIssue,
    CrawlPage,
    CrawlPageImage,
    CrawlPageLink,
    CrawlPageStructuredData,
    Ga4Metric,
    GoogleAccountConfig,
    GscMetric,
    Keyword,
    ProjectAISetting,
    Ranking,
    Snapshot,
    User,
    UserClient,
    db,
)

app = create_app()
migrate = Migrate(app, db)

if __name__ == '__main__':
    app.run()
