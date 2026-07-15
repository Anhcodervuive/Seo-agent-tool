# SEO Agent - Master Roadmap & Progress Report

This document serves as the central source of truth for the overarching architecture, roadmap, and current progress of the SEO Agent project.

---

## 1. Project Overview & Vision
The **SEO Agent** is an automated SEO audit and analysis system. For each client project, it is designed to sequentially collect data from four key sources (Technical Crawl, GA4, GSC, DataForSEO), store dated snapshots, run AI analysis (via LLM), and serve the prioritized results and historical trends through a modern web interface.

### Tech Stack & Tools
- **Backend:** Python (Flask, SQLAlchemy, Gunicorn)
- **Database:** PostgreSQL (Migrated from SQLite for better concurrent performance)
- **Frontend UI:** HTML/CSS (Bootstrap), Jinja2 Templating
- **Crawler Bot:** LibreCrawl (Containerized technical spider)
- **AI Integration:** OpenRouter (LLM access for intelligent analysis)
- **Deployment:** Docker & Docker Compose on Linux VPS (Managed via SSH & Deploy Keys)

---

## 2. The Overarching Phased Plan

The development of the SEO Agent is broken down into 4 strategic phases to ensure stability and scalable delivery.

### 🟢 Phase 1 & 2: The Foundation & Interface (Currently Completed)
**Goal:** Establish the database, the deployment pipeline, the user interface, and the core management logic.
- ✅ **Server & Deployment setup:** Containerized the pipeline and the crawler using Docker. Configured `.env` variables and SSH deploy keys for secure updates.
- ✅ **Project Management (CRUD):** Built the complete interface to Create, Read, Update, and Delete SEO projects.
- ✅ **Advanced Data Fields:** Added `Competitors` tracking and `Crawl Mode` configurations (Full site vs. URL).
- ✅ **Role-Based Access Control (RBAC):** Built a multi-tenant authentication system. Admins can create users, delete users, and assign specific projects to specific users ensuring data privacy.
- ✅ **Database Migration:** Successfully upgraded the local SQLite architecture to a robust PostgreSQL database for the production environment.
- ✅ **Seed Scripts:** Engineered `seed_data.py` to auto-populate the database with dummy projects, keywords, competitors, and snapshots for testing.

### 🟡 Phase 3: Data Aggregation & Crawler Integration (Next Up)
**Goal:** Connect the interface to the data engines to automate the data collection process.
- ⬜ **LibreCrawl Integration:** Wire the "Run Analysis" button to trigger the LibreCrawl container API.
- ⬜ **Data Pipeline Integration:** Implement the scheduled cron jobs (`run_scheduled.sh`) to automatically pull data from Google Analytics 4 (GA4), Google Search Console (GSC), and DataForSEO.
- ⬜ **Snapshot Archiving:** Ensure that all collected metrics are successfully saved into the `snapshots` table in PostgreSQL.

### 🔴 Phase 4: The AI Copilot & Trends Engine (Final Stage)
**Goal:** Give the tool a "Brain" to analyze the raw data and present actionable insights.
- ⬜ **LLM Prompting:** Develop the `analyze.py` script to format the raw data snapshot into a strategic prompt for the OpenRouter LLM.
- ⬜ **Insight Generation:** Capture the LLM's response (Markdown report) and save it to the database.
- ⬜ **Trend Analysis:** Implement the `trends.py` logic to compare the current snapshot against previous months to show traffic, search, and keyword movements.
- ⬜ **Dashboard Rendering:** Serve the AI reports and historical charts beautifully on the client's detail page.

---

## 3. Current Status & Next Action Steps
As of this report, we have successfully completed **100% of Phase 1 and Phase 2**. The environment is live on the test server. 

**Immediate Next Steps for the Development Team:**
We are now entering **Phase 3**. The immediate next task is to begin integrating the `LibreCrawl` container with the Flask application to ensure that clicking "Run Analysis" on the dashboard successfully triggers a technical crawl on the target domain.
