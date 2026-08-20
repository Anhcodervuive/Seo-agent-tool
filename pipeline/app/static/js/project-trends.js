(function () {
    'use strict';

    const CACHE_TTL_MS = 60 * 1000;
    const METRICS = {
        ga4_sessions: {
            label: 'GA4 Sessions',
            source: 'Daily GA4 aggregate',
            color: '#5b8cff',
            fill: 'rgba(91, 140, 255, .16)',
        },
        gsc_clicks: {
            label: 'GSC Clicks',
            source: 'Daily Search Console aggregate',
            color: '#36c7a0',
            fill: 'rgba(54, 199, 160, .16)',
        },
        gsc_ctr: {
            label: 'GSC CTR',
            source: 'Weighted daily Search Console CTR',
            color: '#b58cff',
            fill: 'rgba(181, 140, 255, .16)',
        },
        crawl_issues: {
            label: 'Crawl Issues',
            source: 'Completed-audit observation',
            color: '#fb7185',
            fill: 'rgba(251, 113, 133, .14)',
        },
        backlinks: {
            label: 'Backlinks',
            source: 'Completed-audit observation',
            color: '#f5b84b',
            fill: 'rgba(245, 184, 75, .15)',
        },
    };

    const numberFormatter = new Intl.NumberFormat(undefined, { maximumFractionDigits: 0 });
    const shortDateFormatter = new Intl.DateTimeFormat(undefined, {
        month: 'short', day: 'numeric', timeZone: 'UTC',
    });
    const longDateFormatter = new Intl.DateTimeFormat(undefined, {
        year: 'numeric', month: 'short', day: 'numeric', timeZone: 'UTC',
    });

    function whenDomReady(callback) {
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', callback, { once: true });
            return;
        }
        callback();
    }

    function loadChartJs(url) {
        if (window.Chart) return Promise.resolve(window.Chart);
        if (window.__seoCopilotChartJsPromise) return window.__seoCopilotChartJsPromise;

        window.__seoCopilotChartJsPromise = new Promise((resolve, reject) => {
            const existing = document.querySelector('script[data-seo-copilot-chartjs]');
            if (existing) {
                existing.addEventListener('load', () => resolve(window.Chart), { once: true });
                existing.addEventListener('error', () => reject(new Error('Chart library could not load.')), { once: true });
                return;
            }
            const script = document.createElement('script');
            script.src = url;
            script.async = true;
            script.crossOrigin = 'anonymous';
            script.dataset.seoCopilotChartjs = 'true';
            script.addEventListener('load', () => window.Chart ? resolve(window.Chart) : reject(new Error('Chart library is unavailable.')), { once: true });
            script.addEventListener('error', () => reject(new Error('Chart library could not load.')), { once: true });
            document.head.appendChild(script);
        }).catch((error) => {
            window.__seoCopilotChartJsPromise = null;
            throw error;
        });
        return window.__seoCopilotChartJsPromise;
    }

    function toTimestamp(value) {
        return Date.parse(`${value}T12:00:00Z`);
    }

    function formatNumber(value, metric) {
        if (value == null) return '—';
        if (metric === 'gsc_ctr') return `${Number(value).toFixed(2)}%`;
        return numberFormatter.format(Math.round(Number(value)));
    }

    function formatDelta(value, metric) {
        if (value == null) return '—';
        const prefix = Number(value) > 0 ? '+' : '';
        if (metric === 'gsc_ctr') return `${prefix}${Number(value).toFixed(2)} pts`;
        return `${prefix}${numberFormatter.format(Math.round(Number(value)))}`;
    }

    function formatPercent(value) {
        if (value == null) return '';
        return `${Number(value) > 0 ? '+' : ''}${Number(value).toFixed(1)}%`;
    }

    function formatWindow(windowValue) {
        if (!windowValue || !windowValue.start_date || !windowValue.end_date) return 'Stored data';
        const start = longDateFormatter.format(new Date(`${windowValue.start_date}T12:00:00Z`));
        const end = longDateFormatter.format(new Date(`${windowValue.end_date}T12:00:00Z`));
        return `${start} – ${end}`;
    }

    function changeLabel(comparison, metric) {
        if (!comparison || !comparison.available) return (comparison && comparison.reason) || 'No comparable data yet';
        const delta = formatDelta(comparison.absolute_change, metric);
        const percent = formatPercent(comparison.percent_change);
        return `${comparison.label}: ${delta}${percent ? ` (${percent})` : ''}`;
    }

    function yoyLabel(comparison) {
        if (!comparison || !comparison.available) return 'YoY: unavailable';
        const percent = formatPercent(comparison.percent_change);
        return `YoY: ${percent || 'baseline is zero'}`;
    }

    function trendSvg(points, payload, metric, windowValue) {
        const usable = (points || []).filter((point) => point && point.value != null);
        if (!usable.length) return '<span class="text-muted small">No stored data</span>';
        const values = usable.map((point) => Number(point.value));
        const minValue = Math.min(...values);
        const maxValue = Math.max(...values);
        const range = maxValue - minValue || 1;
        const startDate = (windowValue && windowValue.start_date) || payload.start_date;
        const endDate = (windowValue && windowValue.end_date) || payload.end_date;
        const minTime = toTimestamp(startDate);
        const maxTime = toTimestamp(endDate);
        const timeRange = maxTime - minTime || 1;
        const coords = usable.map((point) => {
            const x = 3 + ((toTimestamp(point.date) - minTime) / timeRange) * 94;
            const y = 55 - ((Number(point.value) - minValue) / range) * 48;
            return `${Math.max(3, Math.min(97, x)).toFixed(1)},${y.toFixed(1)}`;
        }).join(' ');
        const label = (METRICS[metric] || {}).label || 'Trend';
        return `<svg viewBox="0 0 100 62" role="img" aria-label="${label} trend"><line x1="0" x2="100" y1="56" y2="56" stroke="currentColor" opacity=".18"/><polyline points="${coords}" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/></svg>`;
    }

    function chartFallback(points, payload, metric, windowValue) {
        const detail = METRICS[metric] || {};
        return `<div class="trend-chart-fallback-copy"><strong>${detail.label || 'Trend'}</strong><span>Interactive chart is unavailable; the stored time series remains shown below.</span>${trendSvg(points, payload, metric, windowValue)}</div>`;
    }

    function updateTone(element, direction) {
        element.classList.remove('is-up', 'is-down');
        if (direction === 'up') element.classList.add('is-up');
        if (direction === 'down') element.classList.add('is-down');
    }

    whenDomReady(function () {
        const dashboard = document.querySelector('[data-trends-dashboard]');
        if (!dashboard) return;

        const loading = dashboard.querySelector('[data-trends-loading]');
        const content = dashboard.querySelector('[data-trends-content]');
        const status = dashboard.querySelector('[data-trends-status]');
        const detail = dashboard.querySelector('[data-trend-detail]');
        const canvas = dashboard.querySelector('[data-trend-canvas]');
        const chartFallbackElement = dashboard.querySelector('[data-trend-chart-fallback]');
        const detailKicker = dashboard.querySelector('[data-trend-detail-kicker]');
        const detailTitle = dashboard.querySelector('[data-trend-detail-title]');
        const detailCopy = dashboard.querySelector('[data-trend-detail-copy]');
        const detailWindow = dashboard.querySelector('[data-trend-detail-window]');
        const detailMeta = dashboard.querySelector('[data-trend-detail-meta]');
        const dataTable = dashboard.querySelector('[data-trend-data-table]');
        const panel = document.getElementById('trends-panel');
        const cache = new Map();
        let selectedDays = 30;
        let selectedMetric = 'ga4_sessions';
        let activePayload = null;
        let requestController = null;
        let chart = null;
        let detailRenderVersion = 0;

        function isVisible() {
            return panel && !panel.hidden;
        }

        function destroyChart() {
            if (chart) {
                chart.destroy();
                chart = null;
            }
        }

        function renderCards(payload) {
            dashboard.querySelectorAll('[data-trend-card]').forEach((card) => {
                const metric = card.dataset.trendCard;
                const summary = (payload.summary || {})[metric] || {};
                const period = (summary.comparison || {}).period_over_period || {};
                const year = (summary.comparison || {}).year_over_year || {};
                const currentWindow = (period.current || {}).window;
                const active = metric === selectedMetric;
                card.classList.toggle('is-selected', active);
                card.setAttribute('aria-pressed', String(active));
                card.title = `Show ${METRICS[metric].label} chart`;
                card.querySelector('[data-trend-value]').textContent = formatNumber(summary.latest, metric);
                const change = card.querySelector('[data-trend-change]');
                change.textContent = changeLabel(period, metric);
                change.title = period.reason || formatWindow(period.baseline && period.baseline.window);
                updateTone(change, period.health_direction || summary.health_direction || summary.direction);
                const yoy = card.querySelector('[data-trend-yoy]');
                yoy.textContent = yoyLabel(year);
                yoy.title = year.reason || formatWindow(year.baseline && year.baseline.window);
                updateTone(yoy, year.health_direction || 'neutral');
                card.querySelector('[data-trend-chart]').innerHTML = trendSvg((payload.series || {})[metric] || [], payload, metric, currentWindow);
            });
        }

        function renderDataTable(points, metric) {
            if (!points.length) {
                dataTable.innerHTML = '<p class="text-muted small mb-0">No stored observations for this period.</p>';
                return;
            }
            const rows = points.map((point) => {
                const source = point.snapshot_id ? `Snapshot #${point.snapshot_id}` : 'Daily aggregate';
                return `<tr><td>${longDateFormatter.format(new Date(`${point.date}T12:00:00Z`))}</td><td>${formatNumber(point.value, metric)}</td><td>${source}</td></tr>`;
            }).join('');
            dataTable.innerHTML = `<table class="table table-sm trend-data-table mb-0"><thead><tr><th>Date</th><th>Value</th><th>Source</th></tr></thead><tbody>${rows}</tbody></table>`;
        }

        function renderCanvas(ChartJs, points, payload, metric, windowValue) {
            destroyChart();
            const details = METRICS[metric];
            const chartPoints = points.map((point) => ({ x: toTimestamp(point.date), y: Number(point.value) }));
            const prefersReducedMotion = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
            chart = new ChartJs(canvas.getContext('2d'), {
                type: 'line',
                data: {
                    datasets: [{
                        label: details.label,
                        data: chartPoints,
                        borderColor: details.color,
                        backgroundColor: details.fill,
                        borderWidth: 2.5,
                        fill: true,
                        tension: 0.2,
                        pointRadius: chartPoints.length > 45 ? 0 : 3,
                        pointHoverRadius: 5,
                        pointBackgroundColor: details.color,
                    }],
                },
                options: {
                    animation: prefersReducedMotion ? false : { duration: 180 },
                    parsing: false,
                    normalized: true,
                    responsive: true,
                    maintainAspectRatio: false,
                    interaction: { mode: 'nearest', axis: 'x', intersect: false },
                    plugins: {
                        legend: { display: false },
                        decimation: { enabled: chartPoints.length > 180, algorithm: 'min-max' },
                        tooltip: {
                            displayColors: false,
                            callbacks: {
                                title(items) {
                                    return items.length ? longDateFormatter.format(new Date(items[0].parsed.x)) : '';
                                },
                                label(item) {
                                    return `${details.label}: ${formatNumber(item.parsed.y, metric)}`;
                                },
                                afterLabel(item) {
                                    const source = points[item.dataIndex];
                                    return source && source.snapshot_id ? `Snapshot #${source.snapshot_id}` : details.source;
                                },
                            },
                        },
                    },
                    scales: {
                        x: {
                            type: 'linear',
                            min: toTimestamp((windowValue && windowValue.start_date) || payload.start_date),
                            max: toTimestamp((windowValue && windowValue.end_date) || payload.end_date),
                            grid: { color: 'rgba(148, 163, 184, .12)' },
                            ticks: {
                                color: '#94a3b8',
                                maxRotation: 0,
                                sampleSize: 6,
                                maxTicksLimit: 6,
                                callback(value) { return shortDateFormatter.format(new Date(Number(value))); },
                            },
                        },
                        y: {
                            beginAtZero: false,
                            grid: { color: 'rgba(148, 163, 184, .12)' },
                            ticks: {
                                color: '#94a3b8',
                                maxTicksLimit: 5,
                                callback(value) { return formatNumber(value, metric); },
                            },
                        },
                    },
                },
            });
        }

        async function renderDetail(payload) {
            const renderVersion = ++detailRenderVersion;
            const metric = selectedMetric;
            const details = METRICS[metric];
            const summary = (payload.summary || {})[metric] || {};
            const period = (summary.comparison || {}).period_over_period || {};
            const currentWindow = (period.current || {}).window;
            const points = ((payload.series || {})[metric] || []).filter((point) => point.value != null);

            detail.hidden = false;
            detailKicker.textContent = details.source;
            detailTitle.textContent = details.label;
            detailCopy.textContent = changeLabel(period, metric);
            detailWindow.textContent = formatWindow(currentWindow) || `${payload.period_days} days`;
            detailMeta.textContent = `${points.length} stored observation${points.length === 1 ? '' : 's'} shown on their actual dates. ${details.source}.`;
            canvas.setAttribute('aria-label', `${details.label} time series from ${payload.start_date} to ${payload.end_date}`);
            renderDataTable(points, metric);

            if (!points.length) {
                destroyChart();
                canvas.hidden = true;
                chartFallbackElement.hidden = false;
                chartFallbackElement.innerHTML = chartFallback(points, payload, metric, currentWindow);
                return;
            }

            canvas.hidden = false;
            chartFallbackElement.hidden = true;
            chartFallbackElement.innerHTML = '';
            try {
                const ChartJs = await loadChartJs(dashboard.dataset.chartjsUrl);
                if (renderVersion !== detailRenderVersion || metric !== selectedMetric) return;
                renderCanvas(ChartJs, points, payload, metric, currentWindow);
            } catch (error) {
                if (renderVersion !== detailRenderVersion) return;
                destroyChart();
                canvas.hidden = true;
                chartFallbackElement.hidden = false;
                chartFallbackElement.innerHTML = chartFallback(points, payload, metric, currentWindow);
            }
        }

        function render(payload) {
            activePayload = payload;
            renderCards(payload);
            content.hidden = false;
            renderDetail(payload);
            const meta = payload.meta || {};
            status.textContent = `Showing ${payload.period_days} days · ${meta.daily_ga4_points || 0} GA4 daily points · ${meta.daily_gsc_points || 0} GSC daily points · ${meta.available_snapshot_count || 0} audit observations.`;
        }

        function setActivePeriod(days) {
            selectedDays = days;
            dashboard.querySelectorAll('[data-trend-period]').forEach((button) => {
                button.classList.toggle('is-active', Number(button.dataset.trendPeriod) === days);
            });
        }

        function cachedPayload(days) {
            const entry = cache.get(days);
            if (!entry || (Date.now() - entry.loadedAt) > CACHE_TTL_MS) return null;
            return entry.payload;
        }

        async function load(days, options) {
            const settings = options || {};
            setActivePeriod(days);
            const cached = !settings.force && cachedPayload(days);
            if (cached) {
                render(cached);
                return;
            }

            if (requestController) requestController.abort();
            const controller = new AbortController();
            requestController = controller;
            if (!settings.background) {
                loading.hidden = false;
                if (!activePayload) content.hidden = true;
            }
            status.textContent = settings.background ? 'Refreshing stored trend data…' : 'Loading stored trend data…';
            try {
                const response = await fetch(`${dashboard.dataset.trendsUrl}?days=${days}`, {
                    headers: { Accept: 'application/json' },
                    cache: 'no-store',
                    signal: controller.signal,
                });
                if (!response.ok) throw new Error(`Trend request failed: ${response.status}`);
                const payload = await response.json();
                if (requestController !== controller) return;
                cache.set(days, { payload, loadedAt: Date.now() });
                render(payload);
            } catch (error) {
                if (error.name !== 'AbortError') {
                    status.textContent = 'Trend data is temporarily unavailable. Try again in a moment.';
                }
            } finally {
                if (requestController === controller) requestController = null;
                loading.hidden = true;
            }
        }

        function invalidateAndRefresh() {
            cache.clear();
            if (isVisible()) load(selectedDays, { force: true, background: true });
        }

        dashboard.querySelectorAll('[data-trend-period]').forEach((button) => {
            button.addEventListener('click', () => load(Number(button.dataset.trendPeriod)));
        });
        dashboard.querySelectorAll('[data-trend-card]').forEach((card) => {
            card.addEventListener('click', () => {
                selectedMetric = card.dataset.trendCard;
                if (activePayload) render(activePayload);
            });
        });
        document.addEventListener('projecttabchange', (event) => {
            if (event.detail && event.detail.tab === 'trends') load(selectedDays);
        });
        document.addEventListener('projectdatachanged', invalidateAndRefresh);
        window.addEventListener('focus', () => {
            const entry = cache.get(selectedDays);
            if (isVisible() && (!entry || (Date.now() - entry.loadedAt) > CACHE_TTL_MS)) {
                load(selectedDays, { force: true, background: true });
            }
        });
        if (document.querySelector('[data-project-tabs]')?.dataset.initialTab === 'trends') load(selectedDays);
    });
})();
