# SEO Copilot Client User Guide

> A plain-English guide for clients and operations teams. It explains what each screen does, where the data comes from, and what AI Copilot can and cannot do today.

**Version:** 1.1
**Updated:** 25 August 2026
**Audience:** Clients and operations teams
**Scope:** Week 3 Dashboard, audit workflow, trends, keywords, Health Score, and AI Copilot.

## Table of Contents

1. What SEO Copilot helps you do
2. What to prepare before using it
3. A quick map of a Project
4. Run Analysis from start to finish
5. Read Overview and Health Score
6. Read 30/60/90-day trends
7. Track keywords
8. Understand Audit History and Snapshots
9. Use AI SEO Copilot
10. Know exactly what AI is reading
11. Solve common questions and problems
12. Suggested weekly and monthly routine
13. Short glossary

## 1. What SEO Copilot helps you do

SEO Copilot brings the SEO information for one website into one Project. Use it to:

- run a website analysis and save the result;
- review technical issues, traffic, keyword positions, and backlinks;
- compare performance across 30, 60, or 90 days;
- see a single Project Health Score; and
- ask AI Copilot to explain the stored data without manually joining many reports.

In simple terms: **an audit collects the data**, **the dashboard shows the data**, and **AI Copilot helps you understand the data**.

> **Important:** AI Copilot currently reads stored Project data only. Sending a chat message does not start a crawl, request new GA4/Search Console data, change your website, or spend SEO-provider credits.

## 2. What to prepare before using it

You do not need technical SEO knowledge to read the dashboard or chat with AI. To make the data complete, however, an Admin should prepare the Project first.

| Needed item | Why it matters | What happens if it is missing |
| --- | --- | --- |
| Correct website/domain | The crawler needs to know which website to inspect | The audit may target the wrong site or fail |
| Google Analytics 4 (GA4) access | Provides sessions and users | GA4 cards and traffic analysis may be empty |
| Google Search Console (GSC) access | Provides clicks, impressions, CTR, and search position | GSC cards and search analysis may be empty |
| A tracked keyword list | Lets the system measure ranking movement | Keywords tab has little or no useful data |
| At least one completed Full audit | Creates the first crawl, backlink, and Snapshot record | Some dashboard areas will honestly show no data yet |

### Who normally does what?

- **Client or marketing team:** review the dashboard, run audits within the agreed process, read results, ask AI, and assign work.
- **Admin or technical team:** create the Project, connect Google accounts, add keywords/competitors, configure AI, and fix connection problems.

If you are not sure whether GA4 or GSC is connected, open the Project and look at **Project Details** on the Overview tab. Use **Settings** or ask an Admin if anything needs to be changed.

## 3. A quick map of a Project

Each Project has four main tabs.

| Tab | Use it when you want to... | What you will see |
| --- | --- | --- |
| **Overview** | Understand the current situation quickly and ask AI | Health Score, key technical issues, Project details, competitors, and AI Copilot |
| **Trends** | See whether metrics are improving or declining over time | GA4 Sessions, GSC Clicks/CTR, crawl issues, backlinks, and detailed charts |
| **Keywords** | Find rankings that are improving, declining, or close to page 1 | Current/previous position, movement, filters, mini trend, and CSV export |
| **Audit History** | Review previous analysis runs | Saved Snapshots, statuses, and summaries for each audit |

The system does not load every heavy dataset when you first open a Project. Trends, Keywords, and Audit History load only after you open their tab. This keeps the Project responsive even after it has many Snapshots.

## 4. Run Analysis from start to finish

### When should you run it?

- When a Project is new or a data connection was just completed.
- After a major website change: a new template, URL changes, robots.txt changes, redirects, or a large content launch.
- On a regular schedule, usually a Full audit once per month.
- When you only need fresh tracked keyword positions, use **Ranking check only** because it is lighter.

### Steps

1. Open the Project you want to check.
2. Select **Run Analysis** in the top-right corner.
3. Choose the type of run.
4. If you chose a Full audit, select the crawl scope.
5. Confirm the run and follow **Live Analysis Progress** at the top of the page.
6. When it finishes, open Overview, Trends, Keywords, or Audit History to review the newly stored data.

### Which run type should you choose?

| Option | What it does | Best for |
| --- | --- | --- |
| **Full audit** | Crawls the website and collects GA4, GSC, tracked rankings, Project backlinks, and competitor insights | A full monthly review or a major SEO check |
| **Ranking check only** | Refreshes tracked keyword positions, ranking URLs, search volume, and competitor positions only | Fast keyword monitoring without a new crawl, traffic, or backlink collection |

### Choose the crawl scope

| Crawl mode | Plain-English meaning | Use it when |
| --- | --- | --- |
| **Full website** | Crawl the website within the allowed crawl scope | A first audit or a regular complete review |
| **Selected URLs** | Crawl only the full URLs you enter, one per line | Checking specific landing pages or a defined page group |
| **Folder / path** | Crawl one section, such as `/blog/` | The website is large or one section needs attention |
| **Reuse previous crawl** | Skip a new crawl and reuse the last crawl data while other applicable analysis sources may refresh | Technical site structure has not changed and you want a faster run |

> **Tip:** If you are unsure, use **Full audit + Full website**. For a very large website, agree the crawl scope with the technical team first so timing and cost are understood.

### Understand audit statuses

| Status | What it means | What you should do |
| --- | --- | --- |
| **Pending/Running** | The audit is waiting or working | Wait for it to finish; do not submit the same run repeatedly |
| **Complete** | The selected audit stages finished | Review the new data and create an action plan |
| **Partial** | Some data is available, but one or more stages did not finish (for example, a ranking provider or AI report issue) | Use the available data carefully and check which source is missing before concluding |
| **Failed** | The audit did not finish | Tell an Admin the time of the run and share any visible error message or screenshot |

## 5. Read Overview and Health Score

Overview answers a fast question: **Is this website healthy, and what needs attention first?**

### What is Health Score?

Health Score is a 0-100 prioritization score. It brings together four kinds of SEO information:

| Area | Usual weight | Practical meaning |
| --- | ---: | --- |
| **Technical** | 35% | Crawl issues such as page errors, redirects, metadata, and structure signals |
| **Organic** | 30% | GA4 Sessions plus GSC Clicks and CTR trends |
| **Keywords** | 20% | Keyword coverage, Top 10 share, and average positions |
| **Backlinks** | 15% | Change in referring domains/backlinks between audits |

The score does not treat missing data as zero. Instead, it shows **confidence**, meaning how much usable data was available. A new Project can have a score based on only some areas, so do not make a major decision from the score alone.

### Use Health Score well

1. Look at the score and color as an attention signal.
2. Read the Technical, Organic, Keywords, and Backlinks breakdown.
3. Investigate the weakest area using Trends, Keywords, or Website Issues.
4. Ask AI: "Based on the latest Health Score, what are the three most important things to fix first?"
5. After you make website changes, run a new Full audit to create a new Snapshot and a new score.

> **Do not:** treat Health Score as a final verdict or compare two Projects blindly when their confidence levels are very different.

### Website Issues

Website Issues uses the latest completed crawl. It is the best place to find specific technical work. Start with issues affecting many pages, important URLs, or pages that changed after a recent website release.

## 6. Read 30/60/90-day trends

Open **Trends**, choose **30 days**, **60 days**, or **90 days**, then select a metric card to view its larger chart and stored-observation table.

### Five main metrics

| Metric | What it tells you | When it is recorded |
| --- | --- | --- |
| **GA4 Sessions** | Visits/sessions on the website | Daily |
| **GSC Clicks** | Clicks from Google Search to the website | Daily |
| **GSC CTR** | The share of search impressions that turned into clicks | Daily, calculated as a weighted value for accuracy |
| **Crawl Issues** | Number of technical issues found during a crawl | Each completed audit |
| **Backlinks** | Backlink and referring-domain profile | Each completed audit |

### How does the comparison work?

- **30 days:** compared with the immediately preceding 30 days. The interface calls this MoM.
- **60/90 days:** compared with the immediately preceding period of the same length. The interface correctly calls this Period change.
- **YoY:** compared with the matching period last year, only when enough older stored data exists.

For example, the 30-day Sessions card compares the total sessions in the current 30-day period with the previous 30-day period. This is more useful than comparing only the first and last date on a chart.

### Why can 30/60/90 look the same?

This is often correct, not a bug. Crawl issues and backlinks are recorded only when an audit completes. If all available Snapshots are from the last 30 days, every selector may contain the same audit observations.

GA4 and GSC are daily records. Once enough daily history exists, 30/60/90 normally show different date counts and results. If they are empty, read the troubleshooting section below.

### Speed and cost note

Opening Trends does **not** call Google, DataForSEO, or LibreCrawl. It reads stored data only, and the chart library loads only when you open the Trends tab. This keeps the Project fast and avoids unintended provider costs.

## 7. Track keywords

The **Keywords** tab answers: "Which rankings are improving, which are declining, and which ones should I review first?"

### How to use it

1. Open **Keywords**.
2. Search for one keyword when needed.
3. Use filters:
   - **Winners:** ranking position improved;
   - **Losers:** ranking position declined;
   - **Page 1:** rankings already on the first search-results page;
   - **Page 2:** rankings close to page 1 and often good optimization opportunities.
4. Choose a device when the Project has device-specific data.
5. Review Latest position, Previous position, Movement, and the mini trend.
6. Export CSV when you need to share or report outside the system.

### Important notes

- A keyword is saved immediately when it is added to the tracked list.
- Ranking details appear after at least one successful **Ranking check only** or **Full audit**.
- A newly added keyword has no meaningful movement history yet.
- Use **Checks unavailable** when you need to isolate temporary DataForSEO or search-engine problems. Those rows are not included in **Not ranking**.

### Read a keyword result correctly

| What you see | What it means | Best next action |
| --- | --- | --- |
| A number, such as `8` | The checked domain was found at that Google organic position. | Compare it with the previous position and trend. |
| `Not in top 100` | The provider completed the check but did not find the domain in the first 100 organic results checked. | Review relevance, the ranking URL, competitors, and on-page optimization. |
| `Unavailable` / **Checks unavailable** | The provider or search engine did not return a usable result. It does **not** mean the keyword failed to rank. | Wait for the provider to recover, then run **Ranking check only** instead of another Full audit. |

The system compares the returned organic URLs with the Project or competitor
domain itself. This makes normal `www` versus non-`www` website variants less
likely to be mistaken for a missing ranking.

## 8. Understand Audit History and Snapshots

Every audit creates a **Snapshot**. Think of it as a saved picture of SEO conditions at one point in time. It lets you revisit old data and reports instead of overwriting history.

### What does a Snapshot support?

| Snapshot use | Why keeping it matters |
| --- | --- |
| Audit report at that time | You can see the evidence behind a historical report or recommendation |
| Crawl issues | It records technical findings from that specific audit |
| Backlink history | It records the backlink/referring-domain profile at each audit |
| Keyword history | It contributes historical ranking observations |
| Technical/backlink trends | It allows comparison between completed audits |

GA4/GSC trend data is saved separately by calendar day. This prevents traffic or search data from being counted twice when multiple Snapshots cover overlapping date ranges. Therefore, a Snapshot remains valuable even after AI Copilot is available: it is still the historic record for audits, crawl data, and backlinks.

### Read an audit status without guessing

Audit History explains the outcome in plain language and lists the affected
source, retained data, next step, and a collapsible technical detail.

| Status shown | Meaning | What to do |
| --- | --- | --- |
| **Completed** | All selected sources completed and were saved. | Review the Snapshot normally. |
| **Completed with warnings** | Useful audit data was saved, but a non-critical source (for example, a few ranking checks or the AI report) needs attention. | Read the listed source and run only the affected check when appropriate. |
| **Needs attention** | A required stage, usually the website crawl, did not complete reliably. | Read the listed cause, correct it, then run the audit again. |
| **In progress** / **Queued** | The audit has not reached a final state. | Follow Live Analysis Progress rather than starting a duplicate audit. |

For a Full audit, ranking tasks are submitted early and run in parallel with
the crawl and other data collection. Large websites and normal-priority search
engine tasks can still take time; the live panel shows which stage is currently
waiting or collecting results.

> **Be careful when deleting a Snapshot:** it removes that audit record and the data attached to it. Delete only a test or obsolete run after you are certain it is not needed for comparison or reporting.

## 9. Use AI SEO Copilot

AI SEO Copilot is on the **Overview** tab. Use it when you want a data-backed explanation instead of manually joining several reports.

### Steps

1. Open the Overview tab for the correct Project.
2. Type a question or choose a suggested prompt.
3. Send it or press Enter.
4. Wait while it processes. Do not send multiple questions into the same conversation while the current answer is running.
5. Read the answer and its source chips, such as Daily metrics or Snapshot #..., to understand which kind of stored data supported it.

### Good questions to ask

- "Based on the latest Health Score, what should I fix first?"
- "Summarize traffic and Google Search performance for the last 30 days."
- "Which keywords have dropped the most and should be checked first?"
- "What are the most important crawl issues in the latest audit?"
- "How have backlinks and referring domains changed across recent audits?"
- "Compare current organic performance with the previous period and suggest an action plan."

### A short explanation of how AI answers

AI does not receive the entire database at once. When you ask a question, it chooses the relevant stored data area, such as traffic, keywords, crawl issues, or Health Score. The server only gives it data for the Project you are currently viewing, then AI writes a response using those results.

This keeps the answer focused, helps avoid unnecessary data loading, and allows large Projects to remain responsive.

### What AI can and cannot do today

| AI can do | AI cannot do in the current release |
| --- | --- |
| Analyze stored data and answer in the context of the current Project | Start a Full audit or crawl from chat |
| Choose which stored data category to read | Call GA4, GSC, or DataForSEO for live data |
| Summarize keywords, technical issues, traffic, backlinks, competitors, and Health Score | Change the website, add keywords, or modify settings |
| Save the chat history so it remains after a page refresh | Take an outside action without your explicit approval |

> **About the MCP server:** this is a technical building block for possible live AI actions in the future. Clients do not need to install or use it today; the current chat does not call it.

## 10. Know exactly what AI is reading

When the data exists, AI can read the following sources for the Project that is currently open:

| Question type | Data AI may read | Data timing |
| --- | --- | --- |
| Traffic/organic performance | GA4 Sessions and GSC Clicks/Impressions/CTR/Position | Stored daily metrics |
| Keywords | Tracked keyword rankings and movement | Stored ranking results |
| Technical SEO | Crawl issue groups from the latest completed crawl | Latest crawl Snapshot |
| Backlinks | Backlinks and referring domains | Audit Snapshot history |
| Competitors | Project-owned competitor insights | Stored insights |
| Health | Score, component scores, and confidence | Stored Health Score |

If the website changed today, or a Google number changed today, but there has not been an appropriate successful audit/data sync, AI cannot know the new value yet. Run the appropriate audit or ask an Admin to check the connection first.

## 11. Solve common questions and problems

### "AI says there is no data"

The Project may not have a completed Full audit, ranking check, or connected GA4/GSC source. Check Audit History and Project Details first.

### "I cannot send another question right away"

One conversation processes one question at a time so AI does not mix context or create duplicate jobs. Wait for the current answer to finish, then send the next question.

### "GA4/GSC trends are empty"

Common reasons are missing Google access, incorrect Project configuration, or a Project that was audited before daily trend history began. A correctly configured successful Full audit will continue to build history. An Admin can run a targeted backfill when older history is required.

### "30/60/90 days show the same result"

For crawl/backlink values, this can be correct when only a few recent audits exist. For GA4/GSC, check whether enough daily history has been stored.

### "Health Score is low, but we do not have all data yet"

Read both **confidence** and the breakdown. Missing data is not scored as zero, but the score may still represent only part of the picture. Complete the data connections and run more audits before using the score for a major decision.

### "The audit is Partial"

You can still use the data that completed, but treat it as incomplete. Check which source did not finish before comparing it with another Snapshot or making a final recommendation.

## 12. Suggested weekly and monthly routine

### Weekly

1. Open **Keywords** and review Losers and Page 2 opportunities.
2. Open **Trends - 30 days** and check Sessions, Clicks, and CTR.
3. Ask AI: "What changed most in the last 30 days?"
4. Record one to three priority actions, an owner, and a due date.

### Monthly

1. Run a **Full audit** using the agreed scope.
2. Review Health Score and Website Issues.
3. Compare 30/60/90-day trends.
4. Review backlink and keyword movement.
5. Ask AI for a short action plan, then verify the recommended facts against the dashboard and source chips.
6. Keep important Snapshots so you retain a clear reporting history.

## 13. Short glossary

| Term | Plain-English meaning |
| --- | --- |
| **Audit** | One complete SEO analysis run that collects information |
| **Snapshot** | A saved audit checkpoint at a specific time |
| **Crawl** | A bot visits website URLs to find technical signals and issues |
| **GA4 Sessions** | Website visits/sessions reported by Google Analytics 4 |
| **GSC Clicks** | Clicks from Google Search results to your website |
| **CTR** | The percentage of search impressions that became clicks |
| **Keyword movement** | The change in a keyword's ranking position |
| **Backlink** | A link from another website to your website |
| **Referring domain** | A domain with at least one backlink to your website |
| **Health Score** | A combined score used to prioritize SEO work |
| **Confidence** | How complete the data was when the score was calculated |

## Remember these five points

1. To get newer data, run the right audit; chat does not refresh data by itself.
2. To understand change over time, use Trends and select 30/60/90 days.
3. To monitor rankings, use Keywords and start with Losers and Page 2.
4. To ask "why" or "what should we do first?", use AI Copilot, then check the source chips and dashboard.
5. To retain a trustworthy history, keep the important Snapshots in Audit History.
