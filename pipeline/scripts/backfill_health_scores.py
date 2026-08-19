"""Backfill persisted Health Score v2 rows for existing full crawls.

Run inside the application image after the migration:
    python -m scripts.backfill_health_scores
"""

from app import create_app
from app.models import CrawlPage, Snapshot
from services.health import persist_health_score


def main():
    app = create_app()
    with app.app_context():
        snapshots = (
            Snapshot.query.join(CrawlPage, CrawlPage.snapshot_id == Snapshot.id)
            .filter(Snapshot.status.in_(("complete", "partial")))
            .order_by(Snapshot.created_at.asc(), Snapshot.id.asc()).all()
        )
        processed = 0
        for snapshot in snapshots:
            record = persist_health_score(snapshot)
            if record:
                processed += 1
                print(f"snapshot={snapshot.id} score={record.score} confidence={record.confidence}", flush=True)
        print(f"Backfilled {processed} health score(s).", flush=True)


if __name__ == "__main__":
    main()
