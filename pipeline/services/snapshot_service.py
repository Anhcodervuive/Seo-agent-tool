"""Application services for snapshot lifecycle operations."""

import os

from app.models import Snapshot, db


def delete_snapshot(snapshot, report_path=None):
    """Delete a snapshot and its database-owned child data atomically.

    Child rows are removed by PostgreSQL ``ON DELETE CASCADE`` constraints.
    The report file is deleted only after the transaction succeeds.
    """
    snapshot_id = snapshot.id
    db.session.delete(snapshot)
    db.session.commit()
    if report_path and os.path.exists(report_path):
        os.remove(report_path)
    return snapshot_id
