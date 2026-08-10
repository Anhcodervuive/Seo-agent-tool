"""Run and persist a lightweight single-page SEO audit."""
import datetime
import json
import os
import re
import threading
import time
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

import requests

from app.models import OnePageAudit, OnePageFinding, OnePageMetric, db
from services.make_pdf import markdown_to_html


class _PageParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title = ''
        self.meta = {}
        self.headings = {'h1': [], 'h2': []}
        self.images = []
        self.links = []
        self.canonical = None
        self.structured_data = []
        self._stack = []
        self._text_parts = []
        self._title_parts = []
        self._heading_parts = []
        self._script_parts = []
        self._current_heading = None
        self._in_title = False
        self._in_script = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        tag = tag.lower()
        self._stack.append(tag)
        if tag == 'title':
            self._in_title = True
            self._title_parts = []
        elif tag in self.headings:
            self._current_heading = tag
            self._heading_parts = []
        elif tag == 'meta':
            name = (attrs.get('name') or attrs.get('property') or '').lower()
            content = attrs.get('content')
            if name and content is not None:
                self.meta[name] = content.strip()
        elif tag == 'link' and (attrs.get('rel') or '').lower() == 'canonical':
            self.canonical = attrs.get('href')
        elif tag == 'img':
            self.images.append({'src': attrs.get('src'), 'alt': attrs.get('alt')})
        elif tag == 'a' and attrs.get('href'):
            self.links.append({'href': attrs.get('href'), 'text': ''})
        elif tag == 'script' and 'ld+json' in (attrs.get('type') or '').lower():
            self._in_script = True
            self._script_parts = []

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag == 'title':
            self.title = ' '.join(''.join(self._title_parts).split())
            self._in_title = False
        elif tag in self.headings and self._current_heading == tag:
            text = ' '.join(''.join(self._heading_parts).split())
            if text:
                self.headings[tag].append(text)
            self._current_heading = None
        elif tag == 'script' and self._in_script:
            raw = ''.join(self._script_parts).strip()
            if raw:
                try:
                    self.structured_data.append(json.loads(raw))
                except (TypeError, ValueError):
                    pass
            self._in_script = False
        if self._stack:
            self._stack.pop()

    def handle_data(self, data):
        if self._in_title:
            self._title_parts.append(data)
        if self._current_heading:
            self._heading_parts.append(data)
        if self._in_script:
            self._script_parts.append(data)
        if not self._in_script and data.strip():
            self._text_parts.append(data)
        if self.links and self._stack and self._stack[-1] == 'a':
            self.links[-1]['text'] += data

    @property
    def text(self):
        return ' '.join(' '.join(self._text_parts).split())


def _add_finding(audit, findings, category, key, label, status, severity, details, recommendation, evidence=None, order=0):
    finding = OnePageFinding(
        audit_id=audit.id,
        category=category,
        finding_key=key,
        label=label,
        status=status,
        severity=severity,
        details=details,
        recommendation=recommendation,
        evidence=evidence,
        sort_order=order,
    )
    db.session.add(finding)
    findings.append(finding)


def _build_report(audit, page, metrics, findings):
    lines = [
        '# One-Page SEO Analysis',
        '',
        f'**URL:** {audit.url}',
        f'**Score:** {audit.score}/100',
        '',
        '## Summary',
        '',
    ]
    for label, value in metrics:
        lines.append(f'- **{label}:** {value}')
    lines.extend(['', '## Findings', ''])
    for finding in findings:
        lines.extend([
            f'### {finding.label} ({finding.severity.title()})',
            '',
            finding.details or '',
            '',
            f'**Recommendation:** {finding.recommendation}' if finding.recommendation else '',
            '',
        ])
    return '\n'.join(lines)


def _run_audit(app, audit_id):
    with app.app_context():
        audit = db.session.get(OnePageAudit, audit_id)
        if not audit:
            return
        audit.status = 'running'
        audit.started_at = datetime.datetime.utcnow()
        db.session.commit()
        try:
            started = time.perf_counter()
            response = requests.get(
                audit.url,
                timeout=int(os.environ.get('ONE_PAGE_REQUEST_TIMEOUT', '45')),
                headers={'User-Agent': 'SEO-Copilot-One-Page-Audit/1.0'},
                allow_redirects=True,
            )
            elapsed_ms = round((time.perf_counter() - started) * 1000)
            parser = _PageParser()
            parser.feed(response.text)

            final_url = response.url
            page = {
                'url': audit.url,
                'final_url': final_url,
                'status_code': response.status_code,
                'content_type': response.headers.get('Content-Type'),
                'title': parser.title,
                'meta_description': parser.meta.get('description', ''),
                'headings': parser.headings,
                'canonical': urljoin(final_url, parser.canonical) if parser.canonical else None,
                'images': parser.images,
                'links': parser.links,
                'structured_data': parser.structured_data,
                'word_count': len(re.findall(r"\b[\w'-]+\b", parser.text)),
                'response_time_ms': elapsed_ms,
            }
            audit.page_data = page
            audit.source_crawl_id = None

            db.session.query(OnePageFinding).filter_by(audit_id=audit.id).delete()
            db.session.query(OnePageMetric).filter_by(audit_id=audit.id).delete()
            findings = []
            score = 100
            title = parser.title
            description = parser.meta.get('description', '')
            h1s = parser.headings['h1']
            canonical = page['canonical']
            internal_links = [
                link for link in parser.links
                if urlparse(urljoin(final_url, link['href'])).netloc == urlparse(final_url).netloc
            ]
            keyword = (audit.target_keyword or '').strip().lower()
            keyword_hits = parser.text.lower().count(keyword) if keyword else None

            checks = [
                ('technical', 'http_status', 'Page is reachable', response.status_code < 400, 'high', f'HTTP status: {response.status_code}.', 'Fix server or access errors before optimizing the page.'),
                ('meta', 'title_present', 'Title tag is present', bool(title), 'high', 'No title tag was found.', 'Add one clear, descriptive title tag.'),
                ('meta', 'title_length', 'Title length is within a useful range', 30 <= len(title) <= 60, 'medium', f'Title length is {len(title)} characters.', 'Aim for a concise title of roughly 30–60 characters.'),
                ('meta', 'description_present', 'Meta description is present', bool(description), 'high', 'No meta description was found.', 'Add a unique summary that explains the page value.'),
                ('meta', 'description_length', 'Meta description length is reasonable', 70 <= len(description) <= 160, 'low', f'Meta description length is {len(description)} characters.', 'Aim for roughly 70–160 characters and make it specific to this page.'),
                ('headings', 'h1_present', 'A primary H1 heading is present', len(h1s) >= 1, 'high', 'No H1 heading was found.', 'Add one clear H1 that matches the page topic.'),
                ('headings', 'h1_unique', 'The page has one primary H1', len(h1s) == 1, 'medium', f'The page has {len(h1s)} H1 headings.', 'Use one primary H1 and organize supporting content with H2/H3 headings.'),
                ('content', 'word_count', 'The page has substantial readable content', page['word_count'] >= 200, 'medium', f'Visible text contains about {page["word_count"]} words.', 'Add useful, original content that answers the visitor’s intent.'),
                ('images', 'image_alt_text', 'Images have alternative text', all((image.get('alt') or '').strip() for image in parser.images), 'medium', f'{sum(1 for image in parser.images if not (image.get("alt") or "").strip())} of {len(parser.images)} images are missing alt text.', 'Add concise, descriptive alt text where the image conveys information.'),
                ('canonical', 'canonical_present', 'A canonical URL is present', bool(canonical), 'high', 'No canonical URL was found.', 'Add a canonical URL that points to the preferred version of this page.'),
                ('structured_data', 'structured_data_present', 'Structured data is present', bool(parser.structured_data), 'low', f'{len(parser.structured_data)} JSON-LD block(s) were detected.', 'Add valid structured data where it genuinely describes the page.'),
                ('links', 'internal_links', 'The page has internal links', bool(internal_links), 'medium', f'{len(internal_links)} internal link(s) were detected.', 'Add useful internal links to related pages and important conversion paths.'),
                ('performance', 'response_time', 'The page responds quickly', elapsed_ms <= 2000, 'medium', f'Initial response took about {elapsed_ms} ms.', 'Review hosting, caching, assets, and server-side work if response time is high.'),
            ]
            for index, (category, key, label, passed, severity, details, recommendation) in enumerate(checks):
                status = 'pass' if passed else 'warning'
                if not passed:
                    score -= {'high': 10, 'medium': 6, 'low': 3}[severity]
                _add_finding(audit, findings, category, key, label, status, severity if not passed else 'info', details, recommendation, {'passed': passed}, index)

            if keyword:
                passed = keyword_hits > 0
                if not passed:
                    score -= 5
                _add_finding(audit, findings, 'keyword', 'target_keyword_usage', 'Target keyword appears in page content', 'pass' if passed else 'warning', 'medium', f'"{audit.target_keyword}" was found {keyword_hits} time(s) in visible text.', 'Use the target topic naturally in the title, headings, copy, and relevant links.', {'keyword': audit.target_keyword, 'occurrences': keyword_hits}, len(checks))

            score = max(0, min(100, score))
            summary = {'score': score, 'warnings': sum(1 for item in findings if item.status == 'warning'), 'passed': sum(1 for item in findings if item.status == 'pass'), 'images': len(parser.images), 'internal_links': len(internal_links), 'word_count': page['word_count']}
            audit.score = score
            audit.summary = summary
            metric_rows = [
                ('score', 'SEO score', score, '/100'),
                ('http_status', 'HTTP status', response.status_code, None),
                ('title_length', 'Title length', len(title), 'characters'),
                ('meta_description_length', 'Meta description length', len(description), 'characters'),
                ('word_count', 'Visible word count', page['word_count'], 'words'),
                ('h1_count', 'H1 headings', len(h1s), None),
                ('internal_links', 'Internal links', len(internal_links), None),
                ('image_count', 'Images', len(parser.images), None),
                ('response_time', 'Response time', elapsed_ms, 'ms'),
            ]
            for key, label, value, unit in metric_rows:
                db.session.add(OnePageMetric(audit_id=audit.id, metric_key=key, label=label, value=value, unit=unit))

            report_markdown = _build_report(audit, page, [(row[1], f'{row[2]}{(" " + row[3]) if row[3] else ""}') for row in metric_rows], findings)
            reports_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'reports', 'one_page')
            os.makedirs(reports_dir, exist_ok=True)
            markdown_path = os.path.join(reports_dir, f'audit_{audit.id}.md')
            pdf_path = os.path.join(reports_dir, f'audit_{audit.id}.pdf')
            with open(markdown_path, 'w', encoding='utf-8') as report_file:
                report_file.write(report_markdown)
            try:
                from weasyprint import HTML
                HTML(string=markdown_to_html(report_markdown)).write_pdf(pdf_path)
                audit.pdf_path = pdf_path
                audit.error_message = None
            except Exception as pdf_error:
                audit.pdf_path = None
                audit.error_message = f'Analysis completed, but PDF generation is unavailable: {pdf_error}'
            audit.status = 'complete'
            audit.completed_at = datetime.datetime.utcnow()
            db.session.commit()
        except Exception as exc:
            db.session.rollback()
            audit = db.session.get(OnePageAudit, audit_id)
            if audit:
                audit.status = 'failed'
                audit.error_message = str(exc)
                audit.completed_at = datetime.datetime.utcnow()
                db.session.commit()


def enqueue_one_page_audit(app, audit_id):
    worker = threading.Thread(target=_run_audit, args=(app, audit_id), daemon=True)
    worker.start()
    return worker
