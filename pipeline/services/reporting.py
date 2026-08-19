"""Shared report context and artifact contracts.

The current Markdown output remains unchanged for consumers. A sidecar JSON
metadata file makes reports reproducible and gives Week 3/4 a stable place to
store prompt/model/tool-call metadata.
"""

from dataclasses import asdict, dataclass
import datetime
import json
import os


REPORT_PROMPT_VERSION = "seo-report-v1"


@dataclass(frozen=True)
class ReportContext:
    report_type: str
    snapshot_id: int
    client_id: int
    client_name: str
    domain: str
    model_name: str
    prompt_version: str
    created_at: str
    brief: dict


@dataclass(frozen=True)
class ReportArtifact:
    report_type: str
    snapshot_id: int
    markdown_path: str
    metadata_path: str
    model_name: str
    prompt_version: str
    created_at: str

    def to_dict(self):
        return asdict(self)


def build_report_context(client, snapshot, brief, ai_settings, *, report_type="full_snapshot", now=None):
    created_at = (now or datetime.datetime.utcnow()).replace(microsecond=0).isoformat() + "Z"
    return ReportContext(
        report_type=report_type,
        snapshot_id=snapshot.id,
        client_id=client.id,
        client_name=client.name,
        domain=client.domain,
        model_name=ai_settings.get("model_name") or "unknown",
        prompt_version=REPORT_PROMPT_VERSION,
        created_at=created_at,
        brief=brief,
    )


def _safe_filename(value):
    return "_".join(str(value or "client").split())


def write_markdown_report(output_dir, context, content):
    os.makedirs(output_dir, exist_ok=True)
    stem = f"{_safe_filename(context.client_name)}_snapshot{context.snapshot_id}"
    markdown_path = os.path.join(output_dir, f"{stem}.md")
    metadata_path = os.path.join(output_dir, f"{stem}.meta.json")
    with open(markdown_path, "w", encoding="utf-8") as handle:
        handle.write(
            f"# SEO Report - {context.client_name}\n"
            f"_Snapshot {context.snapshot_id} · {context.created_at[:10]}_\n\n"
            f"{content}\n"
        )
    with open(metadata_path, "w", encoding="utf-8") as handle:
        json.dump({**context_to_metadata(context), "markdown_path": markdown_path}, handle, indent=2)
    return ReportArtifact(
        report_type=context.report_type,
        snapshot_id=context.snapshot_id,
        markdown_path=markdown_path,
        metadata_path=metadata_path,
        model_name=context.model_name,
        prompt_version=context.prompt_version,
        created_at=context.created_at,
    )


def context_to_metadata(context):
    data = asdict(context)
    data.pop("brief", None)
    return data

