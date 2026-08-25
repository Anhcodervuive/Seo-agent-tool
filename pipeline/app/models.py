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
    # Country-level Google markets used only for competitor traffic estimates.
    # The primary project location is always included at runtime.
    competitor_traffic_locations = db.Column(db.JSON, nullable=True)
    
    # API Integrations
    google_account_id = db.Column(db.Integer, db.ForeignKey('google_account_configs.id'), nullable=True)
    ga4_property_id = db.Column(db.String(64), nullable=True)
    gsc_site_url = db.Column(db.String(128), nullable=True)
    
    # Crawl Settings
    crawl_mode = db.Column(db.String(64), default='full') # 'full' or 'path'; legacy 'selected' maps to path
    crawl_paths = db.Column(db.Text, nullable=True) # Comma/newline separated path list
    
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)

    google_account = db.relationship('GoogleAccountConfig', backref=db.backref('clients', lazy=True))
    snapshots = db.relationship('Snapshot', back_populates='client', cascade="all, delete-orphan", lazy=True)
    audit_schedules = db.relationship('AuditSchedule', back_populates='client', cascade="all, delete-orphan", lazy=True)
    audit_jobs = db.relationship('AuditJob', back_populates='client', cascade="all, delete-orphan", lazy=True)
    ranking_reconciliation_jobs = db.relationship('RankingReconciliationJob', back_populates='client', cascade="all, delete-orphan", lazy=True)
    one_page_audits = db.relationship('OnePageAudit', back_populates='client', lazy=True)
    keyword_research_runs = db.relationship('KeywordResearchRun', back_populates='client', lazy=True)
    health_scores = db.relationship('HealthScore', back_populates='client', cascade="all, delete-orphan", lazy=True)
    copilot_conversations = db.relationship('CopilotConversation', back_populates='client', cascade="all, delete-orphan", lazy=True)

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
    rankings = db.relationship('Ranking', back_populates='competitor', cascade="all, delete-orphan", lazy=True)
    backlink_history = db.relationship('BacklinkHistory', back_populates='competitor', cascade="all, delete-orphan", lazy=True)
    insights = db.relationship('CompetitorInsight', back_populates='competitor', cascade="all, delete-orphan", lazy=True)
    country_traffic = db.relationship('CompetitorCountryTraffic', back_populates='competitor', cascade="all, delete-orphan", lazy=True)

# ---------------------------------------------------------
# Data Pipeline & Metrics (Historical Snapshots)
# ---------------------------------------------------------

class Snapshot(db.Model):
    __tablename__ = 'snapshots'
    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey('clients.id'), nullable=False)
    librecrawl_crawl_id = db.Column(db.Integer, nullable=True)
    status = db.Column(db.String(64), default='pending') # 'running', 'complete', 'partial', 'failed'
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)

    __table_args__ = (
        db.Index('ix_snapshots_client_created_id', 'client_id', 'created_at', 'id'),
    )

    client = db.relationship('Client', back_populates='snapshots')
    # Snapshot deletion can involve thousands of raw crawl rows.  Keep the ORM
    # cascade semantics, but let PostgreSQL execute the child deletes in-set
    # through their ON DELETE CASCADE foreign keys instead of loading every
    # collection into Python first.
    crawl_issues = db.relationship('CrawlIssue', back_populates='snapshot', cascade="all, delete-orphan", passive_deletes=True, lazy=True)
    crawl_pages = db.relationship('CrawlPage', back_populates='snapshot', cascade="all, delete-orphan", passive_deletes=True, lazy=True)
    crawl_page_links = db.relationship('CrawlPageLink', back_populates='snapshot', cascade="all, delete-orphan", passive_deletes=True, lazy=True)
    crawl_page_images = db.relationship('CrawlPageImage', back_populates='snapshot', cascade="all, delete-orphan", passive_deletes=True, lazy=True)
    crawl_page_structured_data = db.relationship('CrawlPageStructuredData', back_populates='snapshot', cascade="all, delete-orphan", passive_deletes=True, lazy=True)
    ga4_metrics = db.relationship('Ga4Metric', back_populates='snapshot', cascade="all, delete-orphan", passive_deletes=True, lazy=True)
    gsc_metrics = db.relationship('GscMetric', back_populates='snapshot', cascade="all, delete-orphan", passive_deletes=True, lazy=True)
    rankings = db.relationship('Ranking', back_populates='snapshot', cascade="all, delete-orphan", passive_deletes=True, lazy=True)
    backlink_history = db.relationship('BacklinkHistory', back_populates='snapshot', cascade="all, delete-orphan", passive_deletes=True, lazy=True)
    backlink_items = db.relationship('BacklinkItem', back_populates='snapshot', cascade="all, delete-orphan", passive_deletes=True, lazy=True)
    backlink_referring_domains = db.relationship('BacklinkReferringDomain', back_populates='snapshot', cascade="all, delete-orphan", passive_deletes=True, lazy=True)
    backlink_anchors = db.relationship('BacklinkAnchor', back_populates='snapshot', cascade="all, delete-orphan", passive_deletes=True, lazy=True)
    competitor_insights = db.relationship('CompetitorInsight', back_populates='snapshot', cascade="all, delete-orphan", passive_deletes=True, lazy=True)
    competitor_country_traffic = db.relationship('CompetitorCountryTraffic', back_populates='snapshot', cascade="all, delete-orphan", passive_deletes=True, lazy=True)
    audit_job = db.relationship('AuditJob', back_populates='snapshot', cascade="all, delete-orphan", passive_deletes=True, uselist=False)
    ranking_reconciliation_job = db.relationship('RankingReconciliationJob', back_populates='snapshot', cascade="all, delete-orphan", passive_deletes=True, uselist=False)
    health_score = db.relationship('HealthScore', back_populates='snapshot', cascade="all, delete-orphan", passive_deletes=True, uselist=False)


class HealthScore(db.Model):
    """Versioned project-health calculation tied to one completed full audit."""
    __tablename__ = 'health_scores'

    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey('clients.id', ondelete='CASCADE'), nullable=False, index=True)
    snapshot_id = db.Column(db.Integer, db.ForeignKey('snapshots.id', ondelete='CASCADE'), nullable=False, unique=True, index=True)
    score = db.Column(db.Integer, nullable=True)
    label = db.Column(db.String(32), nullable=False, default='No data')
    tone = db.Column(db.String(16), nullable=False, default='neutral')
    confidence = db.Column(db.Integer, nullable=False, default=0)
    algorithm_version = db.Column(db.String(32), nullable=False, default='v2')
    components = db.Column(db.JSON, nullable=False, default=dict)
    factors = db.Column(db.JSON, nullable=False, default=list)
    calculated_at = db.Column(db.DateTime, default=datetime.datetime.utcnow, nullable=False)

    __table_args__ = (
        db.Index('ix_health_scores_client_calculated', 'client_id', 'calculated_at', 'id'),
    )

    client = db.relationship('Client', back_populates='health_scores')
    snapshot = db.relationship('Snapshot', back_populates='health_score')


class CopilotConversation(db.Model):
    """A project-scoped chat thread. Project scope is never model supplied."""
    __tablename__ = 'copilot_conversations'

    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey('clients.id', ondelete='CASCADE'), nullable=False, index=True)
    created_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True, index=True)
    title = db.Column(db.String(160), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow, nullable=False, index=True)

    client = db.relationship('Client', back_populates='copilot_conversations')
    created_by = db.relationship('User', backref=db.backref('copilot_conversations', lazy=True))
    messages = db.relationship('CopilotMessage', back_populates='conversation', cascade="all, delete-orphan", lazy=True)
    runs = db.relationship('CopilotRun', back_populates='conversation', cascade="all, delete-orphan", lazy=True)


class CopilotMessage(db.Model):
    __tablename__ = 'copilot_messages'

    id = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(db.Integer, db.ForeignKey('copilot_conversations.id', ondelete='CASCADE'), nullable=False, index=True)
    role = db.Column(db.String(16), nullable=False)  # user, assistant, tool
    content = db.Column(db.Text, nullable=False, default='')
    citations = db.Column(db.JSON, nullable=False, default=list)
    metadata_json = db.Column('metadata', db.JSON, nullable=False, default=dict)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow, nullable=False, index=True)

    __table_args__ = (
        db.Index('ix_copilot_messages_conversation_id_id', 'conversation_id', 'id'),
    )

    conversation = db.relationship('CopilotConversation', back_populates='messages')


class CopilotRun(db.Model):
    """Durable, asynchronous execution record for a single user message."""
    __tablename__ = 'copilot_runs'

    id = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(db.Integer, db.ForeignKey('copilot_conversations.id', ondelete='CASCADE'), nullable=False, index=True)
    client_id = db.Column(db.Integer, db.ForeignKey('clients.id', ondelete='CASCADE'), nullable=False, index=True)
    requested_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True, index=True)
    user_message_id = db.Column(db.Integer, db.ForeignKey('copilot_messages.id', ondelete='SET NULL'), nullable=True, index=True)
    status = db.Column(db.String(16), nullable=False, default='pending', index=True)
    model_name = db.Column(db.String(160), nullable=True)
    error_message = db.Column(db.Text, nullable=True)
    started_at = db.Column(db.DateTime, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow, nullable=False, index=True)

    __table_args__ = (
        db.Index('ix_copilot_runs_pending', 'status', 'created_at', 'id'),
    )

    conversation = db.relationship('CopilotConversation', back_populates='runs')
    requested_by = db.relationship('User', backref=db.backref('copilot_runs', lazy=True))
    user_message = db.relationship('CopilotMessage', foreign_keys=[user_message_id])
    invocations = db.relationship('CopilotToolInvocation', back_populates='run', cascade="all, delete-orphan", lazy=True)


class CopilotToolInvocation(db.Model):
    __tablename__ = 'copilot_tool_invocations'

    id = db.Column(db.Integer, primary_key=True)
    run_id = db.Column(db.Integer, db.ForeignKey('copilot_runs.id', ondelete='CASCADE'), nullable=False, index=True)
    tool_name = db.Column(db.String(80), nullable=False)
    status = db.Column(db.String(16), nullable=False)
    arguments = db.Column(db.JSON, nullable=False, default=dict)
    result_meta = db.Column(db.JSON, nullable=False, default=dict)
    error_message = db.Column(db.Text, nullable=True)
    duration_ms = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow, nullable=False)

    run = db.relationship('CopilotRun', back_populates='invocations')


class AuditSchedule(db.Model):
    """Recurring full-audit or ranking-only configuration for a project."""
    __tablename__ = 'audit_schedules'

    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey('clients.id', ondelete='CASCADE'), nullable=False, index=True)
    enabled = db.Column(db.Boolean, nullable=False, default=False)
    frequency = db.Column(db.String(16), nullable=False, default='weekly')
    run_type = db.Column(db.String(32), nullable=False, default='full_audit')
    timezone = db.Column(db.String(64), nullable=False, default='Asia/Kolkata')
    run_at_local = db.Column(db.String(5), nullable=False, default='02:00')
    next_run_at = db.Column(db.DateTime, nullable=True, index=True)
    last_run_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow, nullable=False)

    client = db.relationship('Client', back_populates='audit_schedules')
    jobs = db.relationship('AuditJob', back_populates='schedule', lazy=True)


class AuditJob(db.Model):
    """Durable unit of work consumed by the dedicated audit worker."""
    __tablename__ = 'audit_jobs'

    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey('clients.id', ondelete='CASCADE'), nullable=False, index=True)
    snapshot_id = db.Column(db.Integer, db.ForeignKey('snapshots.id', ondelete='CASCADE'), nullable=False, unique=True, index=True)
    schedule_id = db.Column(db.Integer, db.ForeignKey('audit_schedules.id', ondelete='SET NULL'), nullable=True, index=True)
    run_type = db.Column(db.String(32), nullable=False, default='full_audit')
    status = db.Column(db.String(32), nullable=False, default='pending', index=True)
    options = db.Column(db.JSON, nullable=True)
    error_message = db.Column(db.Text, nullable=True)
    queued_at = db.Column(db.DateTime, default=datetime.datetime.utcnow, nullable=False, index=True)
    started_at = db.Column(db.DateTime, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)
    scheduled_for = db.Column(db.DateTime, nullable=True)
    heartbeat_at = db.Column(db.DateTime, nullable=True, index=True)
    attempt_count = db.Column(db.Integer, nullable=False, default=0)
    max_attempts = db.Column(db.Integer, nullable=False, default=3)
    available_at = db.Column(db.DateTime, nullable=True, index=True)
    retry_of_job_id = db.Column(db.Integer, db.ForeignKey('audit_jobs.id', ondelete='SET NULL'), nullable=True, index=True)

    __table_args__ = (
        db.UniqueConstraint('schedule_id', 'scheduled_for', name='uq_audit_jobs_schedule_occurrence'),
        db.Index(
            'uq_audit_jobs_active_client',
            'client_id',
            unique=True,
            postgresql_where=db.text("status IN ('pending', 'running')"),
        ),
    )

    client = db.relationship('Client', back_populates='audit_jobs')
    snapshot = db.relationship('Snapshot', back_populates='audit_job')
    schedule = db.relationship('AuditSchedule', back_populates='jobs')


class RankingReconciliationJob(db.Model):
    """Deferred collection work for DataForSEO Standard ranking tasks.

    The primary audit may finish before DataForSEO makes every asynchronous
    task available.  This durable, snapshot-scoped job lets idle workers keep
    collecting those already-paid tasks without re-running crawl or analytics.
    """
    __tablename__ = 'ranking_reconciliation_jobs'

    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey('clients.id', ondelete='CASCADE'), nullable=False, index=True)
    snapshot_id = db.Column(db.Integer, db.ForeignKey('snapshots.id', ondelete='CASCADE'), nullable=False, unique=True, index=True)
    status = db.Column(db.String(32), nullable=False, default='pending', index=True)
    next_poll_at = db.Column(db.DateTime, nullable=True, index=True)
    attempt_count = db.Column(db.Integer, nullable=False, default=0)
    last_error = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow, nullable=False, index=True)
    completed_at = db.Column(db.DateTime, nullable=True)

    __table_args__ = (
        db.Index('ix_ranking_reconciliation_jobs_status_next_poll', 'status', 'next_poll_at'),
    )

    client = db.relationship('Client', back_populates='ranking_reconciliation_jobs')
    snapshot = db.relationship('Snapshot', back_populates='ranking_reconciliation_job')


class OnePageAudit(db.Model):
    """Persistent audit run for a single user-provided webpage URL."""
    __tablename__ = 'one_page_audits'

    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey('clients.id', ondelete='SET NULL'), nullable=True, index=True)
    created_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True, index=True)
    url = db.Column(db.Text, nullable=False)
    normalized_url = db.Column(db.Text, nullable=False, index=True)
    target_keyword = db.Column(db.String(255), nullable=True)
    status = db.Column(db.String(32), nullable=False, default='pending', index=True)
    score = db.Column(db.Integer, nullable=True)
    summary = db.Column(db.JSON, nullable=True)
    page_data = db.Column(db.JSON, nullable=True)
    pdf_path = db.Column(db.Text, nullable=True)
    error_message = db.Column(db.Text, nullable=True)
    source_crawl_id = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow, nullable=False, index=True)
    started_at = db.Column(db.DateTime, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)

    client = db.relationship('Client', back_populates='one_page_audits')
    created_by = db.relationship('User', backref=db.backref('created_one_page_audits', lazy=True))
    findings = db.relationship('OnePageFinding', back_populates='audit', cascade="all, delete-orphan", lazy=True)
    metrics = db.relationship('OnePageMetric', back_populates='audit', cascade="all, delete-orphan", lazy=True)


class OnePageFinding(db.Model):
    """A single pass, warning, or actionable issue from a one-page audit."""
    __tablename__ = 'one_page_findings'

    id = db.Column(db.Integer, primary_key=True)
    audit_id = db.Column(db.Integer, db.ForeignKey('one_page_audits.id', ondelete='CASCADE'), nullable=False, index=True)
    category = db.Column(db.String(64), nullable=False, index=True)
    finding_key = db.Column(db.String(128), nullable=False)
    label = db.Column(db.String(255), nullable=False)
    status = db.Column(db.String(32), nullable=False, default='warning')
    severity = db.Column(db.String(32), nullable=False, default='info')
    details = db.Column(db.Text, nullable=True)
    recommendation = db.Column(db.Text, nullable=True)
    evidence = db.Column(db.JSON, nullable=True)
    sort_order = db.Column(db.Integer, nullable=True, default=0)

    audit = db.relationship('OnePageAudit', back_populates='findings')


class OnePageMetric(db.Model):
    """A normalized metric used by the one-page report and score."""
    __tablename__ = 'one_page_metrics'

    id = db.Column(db.Integer, primary_key=True)
    audit_id = db.Column(db.Integer, db.ForeignKey('one_page_audits.id', ondelete='CASCADE'), nullable=False, index=True)
    metric_key = db.Column(db.String(128), nullable=False)
    label = db.Column(db.String(255), nullable=False)
    value = db.Column(db.JSON, nullable=True)
    unit = db.Column(db.String(32), nullable=True)

    audit = db.relationship('OnePageAudit', back_populates='metrics')
    __table_args__ = (
        db.UniqueConstraint('audit_id', 'metric_key', name='uq_one_page_metric_audit_key'),
    )


class KeywordResearchRun(db.Model):
    """A durable, standalone keyword-research request.

    Research deliberately does not create a project Snapshot.  A run may be
    associated with a project to make the explicit "Add to Track" hand-off
    convenient, but its ideas and commercial metrics never contribute to
    project rankings, trends, or Health Score by themselves.
    """
    __tablename__ = 'keyword_research_runs'

    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey('clients.id', ondelete='SET NULL'), nullable=True, index=True)
    created_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True, index=True)
    mode = db.Column(db.String(16), nullable=False)  # single or bulk
    input_keywords = db.Column(db.JSON, nullable=False, default=list)
    location = db.Column(db.String(96), nullable=False, default='United States')
    language = db.Column(db.String(20), nullable=False, default='en')
    status = db.Column(db.String(32), nullable=False, default='pending', index=True)
    progress = db.Column(db.JSON, nullable=True)
    summary = db.Column(db.JSON, nullable=True)
    provider_cost = db.Column(db.Float, nullable=False, default=0.0)
    error_message = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow, nullable=False, index=True)
    started_at = db.Column(db.DateTime, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)
    updated_at = db.Column(db.DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow, nullable=False, index=True)

    __table_args__ = (
        db.Index('ix_keyword_research_runs_status_created_id', 'status', 'created_at', 'id'),
    )

    client = db.relationship('Client', back_populates='keyword_research_runs')
    created_by = db.relationship('User', backref=db.backref('keyword_research_runs', lazy=True))
    results = db.relationship('KeywordResearchResult', back_populates='run', cascade='all, delete-orphan', lazy=True)


class KeywordResearchResult(db.Model):
    """One normalized keyword, question, or autocomplete suggestion in a run."""
    __tablename__ = 'keyword_research_results'

    id = db.Column(db.Integer, primary_key=True)
    run_id = db.Column(db.Integer, db.ForeignKey('keyword_research_runs.id', ondelete='CASCADE'), nullable=False, index=True)
    result_type = db.Column(db.String(24), nullable=False, default='keyword', index=True)
    keyword = db.Column(db.String(700), nullable=False)
    source_types = db.Column(db.JSON, nullable=False, default=list)
    source_rank = db.Column(db.Integer, nullable=True)
    search_volume = db.Column(db.Integer, nullable=True)
    keyword_difficulty = db.Column(db.Integer, nullable=True)
    cpc = db.Column(db.Float, nullable=True)
    competition = db.Column(db.Float, nullable=True)
    search_intent = db.Column(db.String(64), nullable=True)
    relevance = db.Column(db.Integer, nullable=True)
    details = db.Column(db.JSON, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow, nullable=False)

    __table_args__ = (
        db.UniqueConstraint('run_id', 'result_type', 'keyword', name='uq_keyword_research_result_run_type_keyword'),
        db.Index('ix_keyword_research_results_run_type_rank', 'run_id', 'result_type', 'source_rank', 'id'),
    )

    run = db.relationship('KeywordResearchRun', back_populates='results')

class CrawlIssue(db.Model):
    __tablename__ = 'crawl_issues'
    id = db.Column(db.Integer, primary_key=True)
    snapshot_id = db.Column(db.Integer, db.ForeignKey('snapshots.id', ondelete='CASCADE'), nullable=False, index=True)
    url = db.Column(db.Text)
    issue = db.Column(db.String(255))
    issue_type = db.Column(db.String(64))
    category = db.Column(db.String(64))
    details = db.Column(db.Text)

    snapshot = db.relationship('Snapshot', back_populates='crawl_issues')


class CrawlPage(db.Model):
    __tablename__ = 'crawl_pages'
    id = db.Column(db.Integer, primary_key=True)
    snapshot_id = db.Column(db.Integer, db.ForeignKey('snapshots.id', ondelete='CASCADE'), nullable=False, index=True)
    url = db.Column(db.Text, nullable=False, index=True)
    status_code = db.Column(db.Integer, nullable=True)
    content_type = db.Column(db.String(255), nullable=True)
    size = db.Column(db.Integer, nullable=True)
    is_internal = db.Column(db.Boolean, nullable=True)
    depth = db.Column(db.Integer, nullable=True)
    title = db.Column(db.Text, nullable=True)
    meta_description = db.Column(db.Text, nullable=True)
    h1 = db.Column(db.Text, nullable=True)
    h2 = db.Column(db.JSON, nullable=True)
    h3 = db.Column(db.JSON, nullable=True)
    word_count = db.Column(db.Integer, nullable=True)
    canonical_url = db.Column(db.Text, nullable=True)
    lang = db.Column(db.String(64), nullable=True)
    charset = db.Column(db.String(64), nullable=True)
    viewport = db.Column(db.Text, nullable=True)
    robots = db.Column(db.Text, nullable=True)
    meta_tags = db.Column(db.JSON, nullable=True)
    og_tags = db.Column(db.JSON, nullable=True)
    twitter_tags = db.Column(db.JSON, nullable=True)
    json_ld = db.Column(db.JSON, nullable=True)
    analytics = db.Column(db.JSON, nullable=True)
    hreflang = db.Column(db.JSON, nullable=True)
    schema_org = db.Column(db.JSON, nullable=True)
    redirects = db.Column(db.JSON, nullable=True)
    linked_from = db.Column(db.JSON, nullable=True)
    external_links = db.Column(db.Integer, nullable=True)
    internal_links = db.Column(db.Integer, nullable=True)
    response_time = db.Column(db.Float, nullable=True)
    javascript_rendered = db.Column(db.Boolean, default=False)
    error_type = db.Column(db.String(128), nullable=True)
    crawled_at = db.Column(db.String(64), nullable=True)

    snapshot = db.relationship('Snapshot', back_populates='crawl_pages')
    images = db.relationship('CrawlPageImage', back_populates='page', cascade="all, delete-orphan", lazy=True)
    structured_data_rows = db.relationship('CrawlPageStructuredData', back_populates='page', cascade="all, delete-orphan", lazy=True)


class CrawlPageLink(db.Model):
    __tablename__ = 'crawl_page_links'
    id = db.Column(db.Integer, primary_key=True)
    snapshot_id = db.Column(db.Integer, db.ForeignKey('snapshots.id', ondelete='CASCADE'), nullable=False, index=True)
    source_url = db.Column(db.Text, nullable=False, index=True)
    target_url = db.Column(db.Text, nullable=False, index=True)
    anchor_text = db.Column(db.Text, nullable=True)
    is_internal = db.Column(db.Boolean, nullable=True)
    target_domain = db.Column(db.String(255), nullable=True)
    target_status = db.Column(db.Integer, nullable=True)
    placement = db.Column(db.String(64), nullable=True)
    discovered_at = db.Column(db.String(64), nullable=True)

    snapshot = db.relationship('Snapshot', back_populates='crawl_page_links')


class CrawlPageImage(db.Model):
    __tablename__ = 'crawl_page_images'
    id = db.Column(db.Integer, primary_key=True)
    snapshot_id = db.Column(db.Integer, db.ForeignKey('snapshots.id', ondelete='CASCADE'), nullable=False, index=True)
    page_id = db.Column(db.Integer, db.ForeignKey('crawl_pages.id'), nullable=True, index=True)
    page_url = db.Column(db.Text, nullable=False, index=True)
    image_url = db.Column(db.Text, nullable=False)
    alt_text = db.Column(db.Text, nullable=True)
    width = db.Column(db.Integer, nullable=True)
    height = db.Column(db.Integer, nullable=True)
    file_size_bytes = db.Column(db.Integer, nullable=True)
    position = db.Column(db.Integer, nullable=True)

    snapshot = db.relationship('Snapshot', back_populates='crawl_page_images')
    page = db.relationship('CrawlPage', back_populates='images')


class CrawlPageStructuredData(db.Model):
    __tablename__ = 'crawl_page_structured_data'
    id = db.Column(db.Integer, primary_key=True)
    snapshot_id = db.Column(db.Integer, db.ForeignKey('snapshots.id', ondelete='CASCADE'), nullable=False, index=True)
    page_id = db.Column(db.Integer, db.ForeignKey('crawl_pages.id'), nullable=True, index=True)
    page_url = db.Column(db.Text, nullable=False, index=True)
    source = db.Column(db.String(32), nullable=False)
    schema_type = db.Column(db.String(255), nullable=True)
    payload = db.Column(db.JSON, nullable=True)
    position = db.Column(db.Integer, nullable=True)

    snapshot = db.relationship('Snapshot', back_populates='crawl_page_structured_data')
    page = db.relationship('CrawlPage', back_populates='structured_data_rows')

class Ga4Metric(db.Model):
    __tablename__ = 'ga4_metrics'
    id = db.Column(db.Integer, primary_key=True)
    snapshot_id = db.Column(db.Integer, db.ForeignKey('snapshots.id', ondelete='CASCADE'), nullable=False, index=True)
    metric_name = db.Column(db.String(64))
    metric_value = db.Column(db.Float)
    dimension = db.Column(db.String(128))
    period_start = db.Column(db.String(64))
    period_end = db.Column(db.String(64))

    snapshot = db.relationship('Snapshot', back_populates='ga4_metrics')

class GscMetric(db.Model):
    __tablename__ = 'gsc_metrics'
    id = db.Column(db.Integer, primary_key=True)
    snapshot_id = db.Column(db.Integer, db.ForeignKey('snapshots.id', ondelete='CASCADE'), nullable=False, index=True)
    # Search queries and page URLs returned by Search Console can exceed 255
    # characters. Keeping these as TEXT prevents a valid live report from
    # failing while its rows are cached for a snapshot.
    query = db.Column(db.Text)
    page = db.Column(db.Text)
    clicks = db.Column(db.Integer)
    impressions = db.Column(db.Integer)
    ctr = db.Column(db.Float)
    position = db.Column(db.Float)
    period_start = db.Column(db.String(64))
    period_end = db.Column(db.String(64))

    snapshot = db.relationship('Snapshot', back_populates='gsc_metrics')


class Ga4DailyMetric(db.Model):
    """One non-overlapping GA4 aggregate per project calendar day."""
    __tablename__ = 'ga4_daily_metrics'

    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey('clients.id', ondelete='CASCADE'), nullable=False, index=True)
    metric_date = db.Column(db.Date, nullable=False, index=True)
    sessions = db.Column(db.Float, nullable=False, default=0)
    total_users = db.Column(db.Float, nullable=False, default=0)
    source_snapshot_id = db.Column(db.Integer, db.ForeignKey('snapshots.id', ondelete='SET NULL'), nullable=True, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow, nullable=False)

    __table_args__ = (
        db.UniqueConstraint('client_id', 'metric_date', name='uq_ga4_daily_metrics_client_date'),
    )


class GscDailyMetric(db.Model):
    """One non-overlapping Search Console aggregate per project calendar day."""
    __tablename__ = 'gsc_daily_metrics'

    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey('clients.id', ondelete='CASCADE'), nullable=False, index=True)
    metric_date = db.Column(db.Date, nullable=False, index=True)
    clicks = db.Column(db.Integer, nullable=False, default=0)
    impressions = db.Column(db.Integer, nullable=False, default=0)
    ctr = db.Column(db.Float, nullable=False, default=0)
    average_position = db.Column(db.Float, nullable=True)
    source_snapshot_id = db.Column(db.Integer, db.ForeignKey('snapshots.id', ondelete='SET NULL'), nullable=True, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow, nullable=False)

    __table_args__ = (
        db.UniqueConstraint('client_id', 'metric_date', name='uq_gsc_daily_metrics_client_date'),
    )

class Ranking(db.Model):
    __tablename__ = 'rankings'
    id = db.Column(db.Integer, primary_key=True)
    snapshot_id = db.Column(db.Integer, db.ForeignKey('snapshots.id', ondelete='CASCADE'), nullable=False, index=True)
    competitor_id = db.Column(db.Integer, db.ForeignKey('competitors.id', ondelete='CASCADE'), nullable=True, index=True)
    keyword = db.Column(db.String(255))
    position = db.Column(db.Integer, nullable=True)
    search_volume = db.Column(db.Integer, nullable=True)
    url = db.Column(db.String(255), nullable=True)
    location = db.Column(db.String(64))
    device = db.Column(db.String(20), default='desktop')
    language = db.Column(db.String(20), default='en')
    check_status = db.Column(db.String(20), nullable=False, default='not_found')
    error_message = db.Column(db.Text, nullable=True)

    snapshot = db.relationship('Snapshot', back_populates='rankings')
    competitor = db.relationship('Competitor', back_populates='rankings')

class BacklinkHistory(db.Model):
    __tablename__ = 'backlink_history'
    id = db.Column(db.Integer, primary_key=True)
    snapshot_id = db.Column(db.Integer, db.ForeignKey('snapshots.id', ondelete='CASCADE'), nullable=False, index=True)
    competitor_id = db.Column(db.Integer, db.ForeignKey('competitors.id', ondelete='CASCADE'), nullable=True, index=True)
    total_backlinks = db.Column(db.Integer, default=0)
    referring_domains = db.Column(db.Integer, default=0)
    new_backlinks = db.Column(db.Integer, default=0)
    lost_backlinks = db.Column(db.Integer, default=0)

    snapshot = db.relationship('Snapshot', back_populates='backlink_history')
    competitor = db.relationship('Competitor', back_populates='backlink_history')


class BacklinkItem(db.Model):
    """A stored sample of live backlinks for the project's domain in a snapshot."""
    __tablename__ = 'backlink_items'

    id = db.Column(db.Integer, primary_key=True)
    snapshot_id = db.Column(db.Integer, db.ForeignKey('snapshots.id', ondelete='CASCADE'), nullable=False, index=True)
    source_domain = db.Column(db.String(255), nullable=True, index=True)
    source_url = db.Column(db.Text, nullable=True)
    domain_rank = db.Column(db.Integer, nullable=True)
    anchor_text = db.Column(db.Text, nullable=True)
    target_url = db.Column(db.Text, nullable=True)
    is_dofollow = db.Column(db.Boolean, nullable=True)
    first_seen = db.Column(db.String(64), nullable=True)
    last_seen = db.Column(db.String(64), nullable=True)
    links_count = db.Column(db.Integer, nullable=True)

    snapshot = db.relationship('Snapshot', back_populates='backlink_items')


class BacklinkReferringDomain(db.Model):
    """A stored sample of referring domains for the project's domain in a snapshot."""
    __tablename__ = 'backlink_referring_domains'

    id = db.Column(db.Integer, primary_key=True)
    snapshot_id = db.Column(db.Integer, db.ForeignKey('snapshots.id', ondelete='CASCADE'), nullable=False, index=True)
    domain = db.Column(db.String(255), nullable=False, index=True)
    backlinks = db.Column(db.Integer, default=0)
    domain_rank = db.Column(db.Integer, nullable=True)
    domain_created_at = db.Column(db.String(64), nullable=True)
    domain_age_years = db.Column(db.Float, nullable=True)
    first_seen = db.Column(db.String(64), nullable=True)

    snapshot = db.relationship('Snapshot', back_populates='backlink_referring_domains')


class BacklinkAnchor(db.Model):
    """A stored sample of anchor text aggregates for the project's domain in a snapshot."""
    __tablename__ = 'backlink_anchors'

    id = db.Column(db.Integer, primary_key=True)
    snapshot_id = db.Column(db.Integer, db.ForeignKey('snapshots.id', ondelete='CASCADE'), nullable=False, index=True)
    anchor_text = db.Column(db.Text, nullable=True)
    referring_domains = db.Column(db.Integer, default=0)
    backlinks = db.Column(db.Integer, default=0)
    first_seen = db.Column(db.String(64), nullable=True)
    lost_date = db.Column(db.String(64), nullable=True)

    snapshot = db.relationship('Snapshot', back_populates='backlink_anchors')


class CompetitorInsight(db.Model):
    """Cached SEO intelligence collected for a competitor during a snapshot."""
    __tablename__ = 'competitor_insights'

    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey('clients.id', ondelete='CASCADE'), nullable=False, index=True)
    competitor_id = db.Column(db.Integer, db.ForeignKey('competitors.id', ondelete='CASCADE'), nullable=False, index=True)
    snapshot_id = db.Column(db.Integer, db.ForeignKey('snapshots.id', ondelete='CASCADE'), nullable=True, index=True)
    target_domain = db.Column(db.String(255), nullable=False)
    status = db.Column(db.String(32), nullable=False, default='complete', index=True)
    summary = db.Column(db.JSON, nullable=True)
    ranked_keywords = db.Column(db.JSON, nullable=True)
    top_pages = db.Column(db.JSON, nullable=True)
    error_message = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow, nullable=False, index=True)

    competitor = db.relationship('Competitor', back_populates='insights')
    client = db.relationship('Client', backref=db.backref('competitor_insights', lazy=True))
    snapshot = db.relationship('Snapshot', back_populates='competitor_insights')


class CompetitorCountryTraffic(db.Model):
    """Estimated organic visibility for one competitor in one Google market."""
    __tablename__ = 'competitor_country_traffic'

    id = db.Column(db.Integer, primary_key=True)
    snapshot_id = db.Column(db.Integer, db.ForeignKey('snapshots.id', ondelete='CASCADE'), nullable=False, index=True)
    competitor_id = db.Column(db.Integer, db.ForeignKey('competitors.id', ondelete='CASCADE'), nullable=False, index=True)
    location = db.Column(db.String(64), nullable=False, index=True)
    estimated_organic_traffic = db.Column(db.Float, nullable=True)
    organic_keyword_count = db.Column(db.Integer, nullable=True)
    top_10_keyword_count = db.Column(db.Integer, nullable=True)
    estimated_traffic_cost = db.Column(db.Float, nullable=True)
    status = db.Column(db.String(20), nullable=False, default='complete')
    error_message = db.Column(db.Text, nullable=True)

    snapshot = db.relationship('Snapshot', back_populates='competitor_country_traffic')
    competitor = db.relationship('Competitor', back_populates='country_traffic')

# ---------------------------------------------------------
# Alerts & Notifications
# ---------------------------------------------------------

class Alert(db.Model):
    __tablename__ = 'alerts'
    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey('clients.id'), nullable=False)
    title = db.Column(db.String(128), nullable=False)
    message = db.Column(db.Text, nullable=False)
    level = db.Column(db.String(20), default='info') # 'info', 'warning', 'critical'
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    
    client = db.relationship('Client', backref=db.backref('alerts', lazy=True, cascade="all, delete-orphan"))

# ---------------------------------------------------------
# AI & Prompts
# ---------------------------------------------------------

class AISetting(db.Model):
    __tablename__ = 'ai_settings'
    id = db.Column(db.Integer, primary_key=True)
    model_name = db.Column(db.String(64), default='z-ai/glm-5.2')
    system_prompt = db.Column(db.Text, default='You are an expert SEO Copilot.')


class ProjectAISetting(db.Model):
    __tablename__ = 'project_ai_settings'
    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey('clients.id'), nullable=False, unique=True)
    model_name = db.Column(db.String(64), nullable=True)
    system_prompt = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    client = db.relationship('Client', backref=db.backref('ai_override', uselist=False, cascade="all, delete-orphan"))


class GoogleAccountConfig(db.Model):
    __tablename__ = 'google_account_configs'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), nullable=False)
    service_email = db.Column(db.String(255), nullable=True)
    credentials_path = db.Column(db.String(512), nullable=False)
    stored_filename = db.Column(db.String(255), nullable=True)
    is_default = db.Column(db.Boolean, default=False)
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
