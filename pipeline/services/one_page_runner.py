"""Run and persist a comprehensive single-page SEO audit."""
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
        self.og_tags = {}
        self.twitter_tags = {}
        self.headings = {'h1': [], 'h2': [], 'h3': []}
        self.images = []
        self.links = []
        self.canonical = None
        self.structured_data = []
        self.schema_types = []
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
            name = (attrs.get('name') or attrs.get('property') or '').lower().strip()
            content = attrs.get('content')
            if name and content is not None:
                content_clean = content.strip()
                self.meta[name] = content_clean
                if name.startswith('og:'):
                    self.og_tags[name] = content_clean
                elif name.startswith('twitter:'):
                    self.twitter_tags[name] = content_clean
        elif tag == 'link' and (attrs.get('rel') or '').lower() == 'canonical':
            self.canonical = attrs.get('href')
        elif tag == 'img':
            src = attrs.get('src') or attrs.get('data-src') or ''
            alt = attrs.get('alt')
            self.images.append({
                'src': src,
                'alt': alt if alt is not None else '',
                'has_alt': bool(alt and alt.strip()),
            })
        elif tag == 'a' and attrs.get('href'):
            self.links.append({'href': attrs.get('href'), 'text': '', 'rel': attrs.get('rel') or ''})
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
                    parsed = json.loads(raw)
                    self.structured_data.append(parsed)
                    self._extract_schema_types(parsed)
                except (TypeError, ValueError):
                    pass
            self._in_script = False
        if self._stack:
            self._stack.pop()

    def _extract_schema_types(self, payload):
        if isinstance(payload, dict):
            type_val = payload.get('@type') or payload.get('type')
            if isinstance(type_val, list):
                for item in type_val:
                    if item and str(item) not in self.schema_types:
                        self.schema_types.append(str(item))
            elif type_val and str(type_val) not in self.schema_types:
                self.schema_types.append(str(type_val))
            if '@graph' in payload and isinstance(payload['@graph'], list):
                for item in payload['@graph']:
                    self._extract_schema_types(item)
        elif isinstance(payload, list):
            for item in payload:
                self._extract_schema_types(item)

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


def _add_finding(audit, findings, category, key, label, status, severity, details, recommendation=None, evidence=None, order=0):
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


def _build_report(audit, page, metrics, findings, seo_elements):
    lines = [
        '# One-Page SEO Analysis Report',
        '',
        f'**Audited URL:** {audit.url}',
        f'**Final URL:** {page.get("final_url", audit.url)}',
        f'**Overall SEO Health Score:** {audit.score}/100',
        f'**Generated At:** {datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")}',
        '',
    ]
    if audit.target_keyword:
        lines.extend([f'**Target Keyword:** `{audit.target_keyword}`', ''])

    lines.extend([
        '## 1. Key Performance & SEO Metrics',
        '',
    ])
    for label, value in metrics:
        lines.append(f'- **{label}:** {value}')

    lines.extend([
        '',
        '## 2. Actual On-Page SEO Elements',
        '',
        'This section presents the actual values extracted directly from the webpage for SEO review and verification:',
        '',
    ])

    # 1. Title
    title_el = seo_elements.get('title', {})
    lines.extend([
        '### Title Tag',
        f'- **Actual Value:** {repr(title_el.get("value")) if title_el.get("value") else "*(Missing)*"}',
        f'- **Character Count:** {title_el.get("length", 0)} characters (Optimal range: 30–65 characters)',
        f'- **Status:** {title_el.get("status", "info").upper()}',
    ])
    if title_el.get('recommendation'):
        lines.append(f'- **Recommendation:** {title_el["recommendation"]}')
    lines.append('')

    # 2. Meta Description
    desc_el = seo_elements.get('meta_description', {})
    lines.extend([
        '### Meta Description',
        f'- **Actual Value:** {repr(desc_el.get("value")) if desc_el.get("value") else "*(Missing)*"}',
        f'- **Character Count:** {desc_el.get("length", 0)} characters (Optimal range: 70–165 characters)',
        f'- **Status:** {desc_el.get("status", "info").upper()}',
    ])
    if desc_el.get('recommendation'):
        lines.append(f'- **Recommendation:** {desc_el["recommendation"]}')
    lines.append('')

    # 3. Headings (H1)
    h1_el = seo_elements.get('h1', {})
    h1_list = h1_el.get('h1_list', [])
    lines.extend([
        '### H1 Headings',
        f'- **H1 Count:** {len(h1_list)} heading(s)',
        f'- **Status:** {h1_el.get("status", "info").upper()}',
    ])
    if h1_list:
        lines.append('- **Actual H1 Tags:**')
        for h in h1_list:
            lines.append(f'  - `{h}`')
    else:
        lines.append('- **Actual H1 Tags:** *(None found)*')
    if h1_el.get('recommendation'):
        lines.append(f'- **Recommendation:** {h1_el["recommendation"]}')
    lines.append('')

    # 4. Canonical
    canonical_el = seo_elements.get('canonical', {})
    lines.extend([
        '### Canonical Tag',
        f'- **Actual Value:** `{canonical_el.get("value") or "None (Missing)"}`',
        f'- **Matches Audited URL:** {"Yes" if canonical_el.get("matches_url") else "No / Custom target"}',
        f'- **Status:** {canonical_el.get("status", "info").upper()}',
    ])
    if canonical_el.get('recommendation'):
        lines.append(f'- **Recommendation:** {canonical_el["recommendation"]}')
    lines.append('')

    # 5. Robots Meta
    robots_el = seo_elements.get('robots', {})
    lines.extend([
        '### Robots Meta Directives',
        f'- **Actual Meta Tag:** `{robots_el.get("value")}`' if robots_el.get('present') else '- **Actual Meta Tag:** *(No robots meta tag found)*',
        f'- **Effective Default:** `{robots_el.get("effective_value", "index, follow")}`',
        f'- **Indexable by Search Engines:** {"Yes" if robots_el.get("is_indexable", True) else "NO (Blocked by noindex)"}',
        f'- **Status:** {robots_el.get("status", "info").upper()}',
    ])
    if robots_el.get('recommendation'):
        lines.append(f'- **Recommendation:** {robots_el["recommendation"]}')
    lines.append('')

    # 6. Images & Alt Text
    img_el = seo_elements.get('images', {})
    lines.extend([
        '### Image Optimization & Alt Text',
        f'- **Total Images Found:** {img_el.get("total", 0)}',
        f'- **Images with Alt Text:** {img_el.get("with_alt", 0)}',
        f'- **Images Missing Alt Text:** {img_el.get("missing_alt", 0)}',
        f'- **Status:** {img_el.get("status", "info").upper()}',
    ])
    if img_el.get('recommendation'):
        lines.append(f'- **Recommendation:** {img_el["recommendation"]}')
    if img_el.get('items'):
        lines.append('- **Actual Images and Alt Text:**')
        for image in img_el['items']:
            alt = image.get('alt', '').strip() or '*(Missing)*'
            lines.append(f'  - `{image.get("src", "")}` — Alt: {alt}')
    lines.append('')

    # 7. Structured Data (Schema)
    schema_el = seo_elements.get('schema', {})
    lines.extend([
        '### Structured Data (JSON-LD Schema)',
        f'- **Detected Schema Types:** {", ".join(f"`{t}`" for t in schema_el.get("types", [])) if schema_el.get("types") else "None detected"}',
        f'- **JSON-LD Blocks:** {schema_el.get("count", 0)} block(s)',
        f'- **Status:** {schema_el.get("status", "info").upper()}',
    ])
    if schema_el.get('recommendation'):
        lines.append(f'- **Recommendation:** {schema_el["recommendation"]}')
    lines.append('')

    # 8. Open Graph & Social
    og_el = seo_elements.get('open_graph', {})
    lines.extend([
        '### Open Graph & Social Metadata',
        f'- **og:title:** {repr(og_el.get("og_title")) if og_el.get("og_title") else "*(Missing)*"}',
        f'- **og:description:** {repr(og_el.get("og_description")) if og_el.get("og_description") else "*(Missing)*"}',
        f'- **og:image:** `{og_el.get("og_image") or "Missing"}`',
        f'- **Twitter Card:** `{og_el.get("twitter_card") or "None"}`',
        f'- **Status:** {og_el.get("status", "info").upper()}',
    ])
    if og_el.get('recommendation'):
        lines.append(f'- **Recommendation:** {og_el["recommendation"]}')
    lines.append('')

    # 9. Internal Links
    links_el = seo_elements.get('links', {})
    lines.extend([
        '### Link Graph',
        f'- **Internal Links:** {links_el.get("internal_count", 0)}',
        f'- **External Links:** {links_el.get("external_count", 0)}',
        f'- **Total Links:** {links_el.get("total_count", 0)}',
        f'- **Status:** {links_el.get("status", "info").upper()}',
    ])
    if links_el.get('recommendation'):
        lines.append(f'- **Recommendation:** {links_el["recommendation"]}')
    if links_el.get('internal_links'):
        lines.append('- **Actual Internal Links:**')
        for link in links_el['internal_links']:
            lines.append(f'  - `{link.get("href", "")}` — {link.get("text") or "(no anchor text)"}')
    lines.append('')

    # 10. Content & Word Count
    content_el = seo_elements.get('content', {})
    lines.extend([
        '### Content Analysis',
        f'- **Word Count:** {content_el.get("word_count", 0)} words',
        f'- **Estimated Reading Time:** ~{content_el.get("reading_time_min", 1)} minute(s)',
        f'- **Actual Text Sample:** {repr(content_el.get("text_preview", ""))}',
        f'- **Status:** {content_el.get("status", "info").upper()}',
    ])
    if content_el.get('recommendation'):
        lines.append(f'- **Recommendation:** {content_el["recommendation"]}')
    lines.append('')

    # 11. Target Keyword
    if audit.target_keyword:
        kw_el = seo_elements.get('keyword', {})
        lines.extend([
            f'### Target Keyword Optimization (`{audit.target_keyword}`)',
            f'- **In Title Tag:** {"Yes ✓" if kw_el.get("in_title") else "No ✗"}',
            f'- **In Meta Description:** {"Yes ✓" if kw_el.get("in_meta") else "No ✗"}',
            f'- **In H1 Heading:** {"Yes ✓" if kw_el.get("in_h1") else "No ✗"}',
            f'- **Body Text Occurrences:** {kw_el.get("body_count", 0)} time(s) (Density: {kw_el.get("density_pct", 0)}%)',
        ])
        if kw_el.get('recommendation'):
            lines.append(f'- **Recommendation:** {kw_el["recommendation"]}')
        lines.append('')

    lines.extend([
        '## 3. Prioritized Action Items & Findings',
        '',
    ])
    warnings = [f for f in findings if f.status == 'warning']
    if warnings:
        for finding in warnings:
            lines.extend([
                f'### [{finding.severity.upper()}] {finding.label}',
                f'**Details:** {finding.details}',
            ])
            if finding.recommendation:
                lines.append(f'**Recommended Fix:** {finding.recommendation}')
            lines.append('')
    else:
        lines.extend(['All essential SEO checks passed! No critical warnings were found.', ''])

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
                headers={'User-Agent': 'SEO-Copilot-One-Page-Audit/1.0 (compatible; Googlebot/2.1)'},
                allow_redirects=True,
            )
            elapsed_ms = round((time.perf_counter() - started) * 1000)
            parser = _PageParser()
            parser.feed(response.text)

            final_url = response.url
            title = parser.title
            description = parser.meta.get('description', '')
            robots_meta = parser.meta.get('robots')
            robots = robots_meta or 'index, follow'
            canonical = urljoin(final_url, parser.canonical) if parser.canonical else None
            h1s = parser.headings['h1']
            h2s = parser.headings['h2']
            h3s = parser.headings['h3']
            word_count = len(re.findall(r"\b[\w'-]+\b", parser.text))
            reading_time_min = max(1, round(word_count / 200))

            base_netloc = urlparse(final_url).netloc
            internal_links = []
            external_links = []
            for link in parser.links:
                href = link.get('href', '')
                full_href = urljoin(final_url, href)
                link_entry = {
                    'href': full_href,
                    'text': ' '.join(link.get('text', '').split()),
                    'rel': link.get('rel', ''),
                }
                if urlparse(full_href).netloc == base_netloc:
                    internal_links.append(link_entry)
                else:
                    external_links.append(link_entry)

            total_images = len(parser.images)
            images_with_alt = sum(1 for img in parser.images if img.get('has_alt'))
            images_missing_alt = total_images - images_with_alt

            keyword = (audit.target_keyword or '').strip()
            kw_lower = keyword.lower()
            keyword_data = None
            if keyword:
                in_title = kw_lower in title.lower() if title else False
                in_meta = kw_lower in description.lower() if description else False
                in_h1 = any(kw_lower in h.lower() for h in h1s)
                body_count = parser.text.lower().count(kw_lower)
                density_pct = round((body_count / max(1, word_count)) * 100, 2)
                keyword_data = {
                    'keyword': keyword,
                    'in_title': in_title,
                    'in_meta': in_meta,
                    'in_h1': in_h1,
                    'body_count': body_count,
                    'density_pct': density_pct,
                }

            # Build rich structured actual SEO elements dictionary
            seo_elements = {
                'title': {
                    'name': 'Title Tag',
                    'value': title or None,
                    'length': len(title),
                    'status': 'pass' if (30 <= len(title) <= 65) else 'warning',
                    'severity': 'info' if (30 <= len(title) <= 65) else ('high' if not title else 'medium'),
                    'recommendation': None if (30 <= len(title) <= 65) else (
                        'Write a concise, descriptive title tag (30–65 characters) and place it inside <head>.'
                        if not title else
                        f'Shorten the title tag from {len(title)} to under 65 characters to avoid truncation in Google SERPs.'
                        if len(title) > 65 else
                        f'Expand the title from {len(title)} to at least 30 characters with clear brand or topic differentiation.'
                    ),
                },
                'meta_description': {
                    'name': 'Meta Description',
                    'value': description or None,
                    'length': len(description),
                    'status': 'pass' if (70 <= len(description) <= 165) else 'warning',
                    'severity': 'info' if (70 <= len(description) <= 165) else ('high' if not description else 'low'),
                    'recommendation': None if (70 <= len(description) <= 165) else (
                        'Add a unique meta description (70–165 characters) summarizing the value proposition.'
                        if not description else
                        f'Shorten meta description from {len(description)} to under 165 characters to prevent snippet cut-off.'
                        if len(description) > 165 else
                        f'Expand meta description from {len(description)} to at least 70 characters with a clear call-to-action.'
                    ),
                },
                'h1': {
                    'name': 'H1 Heading',
                    'h1_list': h1s,
                    'count': len(h1s),
                    'status': 'pass' if len(h1s) == 1 else 'warning',
                    'severity': 'info' if len(h1s) == 1 else ('high' if len(h1s) == 0 else 'medium'),
                    'recommendation': None if len(h1s) == 1 else (
                        'Add exactly one primary H1 heading to clearly communicate the page topic.'
                        if len(h1s) == 0 else
                        f'Found {len(h1s)} H1 headings. Keep one primary H1 and convert secondary headings to H2 tags.'
                    ),
                },
                'headings': {
                    'h1_count': len(h1s),
                    'h2_count': len(h2s),
                    'h3_count': len(h3s),
                    'h1_items': h1s,
                    'h2_items': h2s[:10],
                    'h3_items': h3s[:10],
                },
                'canonical': {
                    'name': 'Canonical Tag',
                    'value': canonical,
                    'matches_url': bool(canonical and (canonical == final_url or canonical.rstrip('/') == final_url.rstrip('/'))),
                    'status': 'pass' if canonical else 'warning',
                    'severity': 'info' if canonical else 'high',
                    'recommendation': None if canonical else 'Add a self-referencing canonical URL tag inside <head> to prevent duplicate content issues.',
                },
                'robots': {
                    'name': 'Robots Meta',
                    'value': robots_meta,
                    'present': bool(robots_meta),
                    'effective_value': robots,
                    'is_indexable': 'noindex' not in robots.lower(),
                    'status': 'pass' if 'noindex' not in robots.lower() else 'warning',
                    'severity': 'info' if 'noindex' not in robots.lower() else 'high',
                    'recommendation': None if 'noindex' not in robots.lower() else 'Remove the "noindex" directive if you want this page to appear in Google search results.',
                },
                'url': {
                    'name': 'URL & Status',
                    'requested_url': audit.url,
                    'final_url': final_url,
                    'status_code': response.status_code,
                    'response_time_ms': elapsed_ms,
                    'status': 'pass' if response.status_code == 200 and elapsed_ms <= 2500 else 'warning',
                    'severity': 'info' if response.status_code == 200 else 'high',
                    'recommendation': None if response.status_code == 200 else f'Fix HTTP status error ({response.status_code}) on the host server.',
                },
                'images': {
                    'name': 'Images & Alt Text',
                    'total': total_images,
                    'with_alt': images_with_alt,
                    'missing_alt': images_missing_alt,
                    'items': parser.images,
                    'status': 'pass' if images_missing_alt == 0 else 'warning',
                    'severity': 'info' if images_missing_alt == 0 else 'medium',
                    'recommendation': None if images_missing_alt == 0 else f'Add descriptive alt text to the {images_missing_alt} image(s) lacking descriptions.',
                },
                'schema': {
                    'name': 'Structured Data (Schema)',
                    'types': parser.schema_types,
                    'count': len(parser.structured_data),
                    'status': 'pass' if parser.schema_types else 'info',
                    'severity': 'info',
                    'recommendation': None if parser.schema_types else 'Consider adding Schema.org JSON-LD (e.g. Article, Organization, Product) to enhance rich snippets.',
                },
                'open_graph': {
                    'name': 'Open Graph & Social Cards',
                    'og_title': parser.og_tags.get('og:title'),
                    'og_description': parser.og_tags.get('og:description'),
                    'og_image': parser.og_tags.get('og:image'),
                    'og_url': parser.og_tags.get('og:url'),
                    'og_type': parser.og_tags.get('og:type'),
                    'twitter_card': parser.twitter_tags.get('twitter:card'),
                    'twitter_title': parser.twitter_tags.get('twitter:title'),
                    'twitter_description': parser.twitter_tags.get('twitter:description'),
                    'twitter_image': parser.twitter_tags.get('twitter:image'),
                    'status': 'pass' if (parser.og_tags.get('og:title') and parser.og_tags.get('og:image')) else 'warning',
                    'severity': 'info' if (parser.og_tags.get('og:title') and parser.og_tags.get('og:image')) else 'low',
                    'recommendation': None if (parser.og_tags.get('og:title') and parser.og_tags.get('og:image')) else 'Add og:title, og:description, and og:image tags for optimal social sharing display.',
                },
                'links': {
                    'name': 'Links Graph',
                    'internal_count': len(internal_links),
                    'external_count': len(external_links),
                    'total_count': len(parser.links),
                    'internal_links': internal_links,
                    'external_links': external_links,
                    'status': 'pass' if len(internal_links) > 0 else 'warning',
                    'severity': 'info' if len(internal_links) > 0 else 'medium',
                    'recommendation': None if len(internal_links) > 0 else 'Add internal links connecting this page to other relevant sections of your site.',
                },
                'content': {
                    'name': 'Content & Word Count',
                    'word_count': word_count,
                    'reading_time_min': reading_time_min,
                    'text_preview': parser.text[:300] + ('...' if len(parser.text) > 300 else ''),
                    'status': 'pass' if word_count >= 250 else 'warning',
                    'severity': 'info' if word_count >= 250 else 'medium',
                    'recommendation': None if word_count >= 250 else 'Expand page content to at least 250–300 words with helpful, original material.',
                },
            }

            if keyword_data:
                kw_passed = keyword_data['in_title'] or keyword_data['in_h1'] or (keyword_data['body_count'] >= 1)
                seo_elements['keyword'] = {
                    'name': f'Target Keyword: {keyword}',
                    'keyword': keyword,
                    'in_title': keyword_data['in_title'],
                    'in_meta': keyword_data['in_meta'],
                    'in_h1': keyword_data['in_h1'],
                    'body_count': keyword_data['body_count'],
                    'density_pct': keyword_data['density_pct'],
                    'status': 'pass' if kw_passed else 'warning',
                    'severity': 'info' if kw_passed else 'medium',
                    'recommendation': None if kw_passed else f'Include target keyword "{keyword}" naturally in the Title, H1 heading, and page copy.',
                }

            page = {
                'url': audit.url,
                'final_url': final_url,
                'status_code': response.status_code,
                'content_type': response.headers.get('Content-Type'),
                'title': title,
                'meta_description': description,
                'headings': parser.headings,
                'canonical': canonical,
                'images': parser.images,
                'links': parser.links,
                'internal_links': internal_links,
                'external_links': external_links,
                'structured_data': parser.structured_data,
                'schema_types': parser.schema_types,
                'og_tags': parser.og_tags,
                'twitter_tags': parser.twitter_tags,
                'word_count': word_count,
                'reading_time_min': reading_time_min,
                'response_time_ms': elapsed_ms,
                'seo_elements': seo_elements,
            }
            audit.page_data = page
            audit.source_crawl_id = None

            db.session.query(OnePageFinding).filter_by(audit_id=audit.id).delete()
            db.session.query(OnePageMetric).filter_by(audit_id=audit.id).delete()
            findings = []
            score = 100

            # Generate accurate, non-contradictory findings with actual values
            checks = [
                (
                    'technical', 'http_status', 'HTTP Server Response',
                    response.status_code < 400,
                    'high',
                    f'HTTP {response.status_code} ({elapsed_ms} ms) for {final_url}',
                    None if response.status_code < 400 else 'Fix server or routing issues so the page returns HTTP 200 OK.',
                ),
                (
                    'meta', 'title_tag', 'Title Tag',
                    bool(title) and (30 <= len(title) <= 65),
                    'high' if not title else 'medium',
                    f'Title ({len(title)} chars): "{title}"' if title else 'No title tag was found in the HTML document.',
                    seo_elements['title']['recommendation'],
                ),
                (
                    'meta', 'meta_description', 'Meta Description',
                    bool(description) and (70 <= len(description) <= 165),
                    'high' if not description else 'low',
                    f'Meta Description ({len(description)} chars): "{description}"' if description else 'No meta description tag was found on this page.',
                    seo_elements['meta_description']['recommendation'],
                ),
                (
                    'headings', 'h1_heading', 'Primary H1 Heading',
                    len(h1s) == 1,
                    'high' if len(h1s) == 0 else 'medium',
                    f'Found 1 primary H1: "{h1s[0]}"' if len(h1s) == 1 else (f'Found {len(h1s)} H1 headings: {", ".join(repr(h) for h in h1s)}' if len(h1s) > 1 else 'No H1 heading found on the page.'),
                    seo_elements['h1']['recommendation'],
                ),
                (
                    'canonical', 'canonical_tag', 'Canonical URL Tag',
                    bool(canonical),
                    'high',
                    f'Canonical URL is specified: "{canonical}"' if canonical else 'No canonical URL tag found in the document <head>.',
                    seo_elements['canonical']['recommendation'],
                ),
                (
                    'technical', 'robots_directive', 'Robots Meta Directive',
                    'noindex' not in robots.lower(),
                    'high',
                    f'Robots directive: "{robots}" (Page is indexable)' if 'noindex' not in robots.lower() else f'Robots directive: "{robots}" (Search engines are instructed NOT to index this page)',
                    seo_elements['robots']['recommendation'],
                ),
                (
                    'images', 'image_alt_text', 'Image Alt Text Optimization',
                    images_missing_alt == 0,
                    'medium',
                    f'All {total_images} images have descriptive alt text.' if images_missing_alt == 0 else f'{images_missing_alt} of {total_images} images are missing alternative text descriptions.',
                    seo_elements['images']['recommendation'],
                ),
                (
                    'content', 'word_count', 'Content Depth & Word Count',
                    word_count >= 250,
                    'medium',
                    f'Page contains {word_count} readable words (~{reading_time_min} min read).' if word_count >= 250 else f'Page contains only {word_count} words (thin content risk).',
                    seo_elements['content']['recommendation'],
                ),
                (
                    'links', 'internal_links', 'Internal Linking Architecture',
                    len(internal_links) > 0,
                    'medium',
                    f'Found {len(internal_links)} internal link(s) and {len(external_links)} external link(s).' if len(internal_links) > 0 else 'No internal links were detected on this page.',
                    seo_elements['links']['recommendation'],
                ),
                (
                    'structured_data', 'schema_markup', 'Structured Data (Schema.org)',
                    bool(parser.schema_types),
                    'info',
                    f'Detected schema type(s): {", ".join(parser.schema_types)} ({len(parser.structured_data)} JSON-LD blocks).' if parser.schema_types else 'No JSON-LD structured data detected on this page.',
                    seo_elements['schema']['recommendation'],
                ),
                (
                    'social', 'open_graph', 'Open Graph Social Sharing',
                    bool(parser.og_tags.get('og:title') and parser.og_tags.get('og:image')),
                    'low',
                    f'Open Graph tags configured (og:title: "{parser.og_tags.get("og:title", "")}").' if (parser.og_tags.get('og:title') and parser.og_tags.get('og:image')) else 'Incomplete Open Graph tags (missing og:title or og:image).',
                    seo_elements['open_graph']['recommendation'],
                ),
            ]

            for index, (category, key, label, passed, severity, details, recommendation) in enumerate(checks):
                status = 'pass' if passed else 'warning'
                if not passed and severity != 'info':
                    score -= {'high': 12, 'medium': 6, 'low': 3}.get(severity, 3)
                _add_finding(
                    audit, findings, category, key, label, status,
                    severity if not passed else 'info',
                    details, recommendation,
                    {'passed': passed}, index,
                )

            if keyword_data:
                kw_passed = keyword_data['in_title'] or keyword_data['in_h1'] or (keyword_data['body_count'] >= 1)
                if not kw_passed:
                    score -= 8
                kw_details = (
                    f'Target keyword "{keyword}" found {keyword_data["body_count"]} time(s) in copy '
                    f'(Density: {keyword_data["density_pct"]}%). '
                    f'Title: {"✓" if keyword_data["in_title"] else "✗"}, '
                    f'H1: {"✓" if keyword_data["in_h1"] else "✗"}, '
                    f'Meta: {"✓" if keyword_data["in_meta"] else "✗"}.'
                )
                _add_finding(
                    audit, findings, 'keyword', 'target_keyword_usage',
                    f'Target Keyword Optimization ("{keyword}")',
                    'pass' if kw_passed else 'warning',
                    'medium' if not kw_passed else 'info',
                    kw_details,
                    seo_elements.get('keyword', {}).get('recommendation'),
                    keyword_data, len(checks),
                )

            score = max(0, min(100, score))
            summary = {
                'score': score,
                'warnings': sum(1 for item in findings if item.status == 'warning'),
                'passed': sum(1 for item in findings if item.status == 'pass'),
                'images': total_images,
                'images_missing_alt': images_missing_alt,
                'internal_links': len(internal_links),
                'word_count': word_count,
                'schema_types_count': len(parser.schema_types),
            }
            audit.score = score
            audit.summary = summary

            metric_rows = [
                ('score', 'SEO score', score, '/100'),
                ('http_status', 'HTTP status', response.status_code, None),
                ('title_length', 'Title length', len(title), 'characters'),
                ('meta_description_length', 'Meta description length', len(description), 'characters'),
                ('word_count', 'Visible word count', word_count, 'words'),
                ('reading_time', 'Reading time', reading_time_min, 'min'),
                ('h1_count', 'H1 headings', len(h1s), None),
                ('internal_links', 'Internal links', len(internal_links), None),
                ('external_links', 'External links', len(external_links), None),
                ('image_count', 'Images', total_images, None),
                ('images_missing_alt', 'Images missing alt', images_missing_alt, None),
                ('schema_types_count', 'Schema types', len(parser.schema_types), None),
                ('response_time', 'Response time', elapsed_ms, 'ms'),
            ]
            for key, label, value, unit in metric_rows:
                db.session.add(OnePageMetric(audit_id=audit.id, metric_key=key, label=label, value=value, unit=unit))

            report_markdown = _build_report(
                audit, page,
                [(row[1], f'{row[2]}{(" " + row[3]) if row[3] else ""}') for row in metric_rows],
                findings,
                seo_elements,
            )
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
