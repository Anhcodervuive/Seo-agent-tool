import datetime
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()

# ---------------------------------------------------------
# Authentication & Access Control
# ---------------------------------------------------------

class UserClient(db.Model):
    """Association table for mapping users to clients they can access."""
    __tablename__ = 'user_client'
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey('clients.id'), primary_key=True)

class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), default='member') # 'admin' or 'member'
    
    clients = db.relationship('Client', secondary='user_client', backref=db.backref('users', lazy='dynamic'))

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

# ---------------------------------------------------------
# Project / Client Configuration
# ---------------------------------------------------------

class Client(db.Model):
    __tablename__ = 'clients'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), nullable=False)
    domain = db.Column(db.String(128), nullable=False)
    business_context = db.Column(db.Text, nullable=True)
    location = db.Column(db.String(64), default='United States')
    
    # API Integrations
    ga4_property_id = db.Column(db.String(64), nullable=True)
    gsc_site_url = db.Column(db.String(128), nullable=True)
    
    # Crawl Settings
    crawl_mode = db.Column(db.String(64), default='full') # 'full', 'selected', 'path'
    crawl_paths = db.Column(db.Text, nullable=True) # Comma separated list
    
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)

class Keyword(db.Model):
    __tablename__ = 'keywords'
    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey('clients.id'), nullable=False)
    keyword = db.Column(db.String(128), nullable=False)
    location = db.Column(db.String(64), default='United States')
    device = db.Column(db.String(20), default='desktop')
    language = db.Column(db.String(20), default='en')
    priority = db.Column(db.String(20), default='medium') # 'high', 'medium', 'low'
    
    client = db.relationship('Client', backref=db.backref('keywords', lazy=True, cascade="all, delete-orphan"))

class Competitor(db.Model):
    __tablename__ = 'competitors'
    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey('clients.id'), nullable=False)
    domain = db.Column(db.String(128), nullable=False)
    
    client = db.relationship('Client', backref=db.backref('competitors', lazy=True, cascade="all, delete-orphan"))

# ---------------------------------------------------------
# Data Pipeline & Metrics (Historical Snapshots)
# ---------------------------------------------------------

class Snapshot(db.Model):
    __tablename__ = 'snapshots'
    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey('clients.id'), nullable=False)
    status = db.Column(db.String(64), default='pending') # 'running', 'complete', 'partial', 'failed'
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)

class CrawlIssue(db.Model):
    __tablename__ = 'crawl_issues'
    id = db.Column(db.Integer, primary_key=True)
    snapshot_id = db.Column(db.Integer, db.ForeignKey('snapshots.id'), nullable=False)
    url = db.Column(db.Text)
    issue = db.Column(db.String(255))
    issue_type = db.Column(db.String(64))
    category = db.Column(db.String(64))
    details = db.Column(db.Text)

class Ga4Metric(db.Model):
    __tablename__ = 'ga4_metrics'
    id = db.Column(db.Integer, primary_key=True)
    snapshot_id = db.Column(db.Integer, db.ForeignKey('snapshots.id'), nullable=False)
    metric_name = db.Column(db.String(64))
    metric_value = db.Column(db.Float)
    dimension = db.Column(db.String(128))
    period_start = db.Column(db.String(64))
    period_end = db.Column(db.String(64))

class GscMetric(db.Model):
    __tablename__ = 'gsc_metrics'
    id = db.Column(db.Integer, primary_key=True)
    snapshot_id = db.Column(db.Integer, db.ForeignKey('snapshots.id'), nullable=False)
    query = db.Column(db.String(255))
    page = db.Column(db.String(255))
    clicks = db.Column(db.Integer)
    impressions = db.Column(db.Integer)
    ctr = db.Column(db.Float)
    position = db.Column(db.Float)
    period_start = db.Column(db.String(64))
    period_end = db.Column(db.String(64))

class Ranking(db.Model):
    __tablename__ = 'rankings'
    id = db.Column(db.Integer, primary_key=True)
    snapshot_id = db.Column(db.Integer, db.ForeignKey('snapshots.id'), nullable=False)
    keyword = db.Column(db.String(255))
    position = db.Column(db.Integer, nullable=True)
    search_volume = db.Column(db.Integer, nullable=True)
    url = db.Column(db.String(255), nullable=True)
    location = db.Column(db.String(64))
    device = db.Column(db.String(20), default='desktop')

class BacklinkHistory(db.Model):
    __tablename__ = 'backlink_history'
    id = db.Column(db.Integer, primary_key=True)
    snapshot_id = db.Column(db.Integer, db.ForeignKey('snapshots.id'), nullable=False)
    total_backlinks = db.Column(db.Integer, default=0)
    referring_domains = db.Column(db.Integer, default=0)
    new_backlinks = db.Column(db.Integer, default=0)
    lost_backlinks = db.Column(db.Integer, default=0)

# ---------------------------------------------------------
# AI & Prompts
# ---------------------------------------------------------

class AISetting(db.Model):
    __tablename__ = 'ai_settings'
    id = db.Column(db.Integer, primary_key=True)
    model_name = db.Column(db.String(64), default='z-ai/glm-5.2')
    system_prompt = db.Column(db.Text, default='You are an expert SEO Copilot.')
