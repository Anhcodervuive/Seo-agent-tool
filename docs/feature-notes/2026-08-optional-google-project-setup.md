# Optional Google data sources and project settings UX

Projects can now be created and maintained without linking Google Analytics or Google Search Console. Project name and domain are the only required identity fields.

## Behavior

- GA4 and GSC are independent optional data sources.
- A project may use neither source, GA4 only, GSC only, or both.
- Missing Google configuration does not block crawl-based website health checks.
- Clearing a Google property stops future collection for that source. Existing stored history is not deleted.
- Organic metrics become available after the relevant source is configured and a later audit collects data.

## Create Project

The create flow separates project identity, data sources, search tracking, crawl scope, and final review. Data Sources includes a clear **Skip for now** path, and project-specific AI behavior is contained in Advanced AI settings.

## Edit Project

Edit Project is a settings workspace rather than a sequential wizard. Sections can be opened directly, and the sticky action bar reports unsaved and saving states. Crawl paths and schedule controls appear or become active only when their parent option is enabled.

## Verification matrix

Test project creation and editing with:

1. No Google sources.
2. GA4 only.
3. GSC only.
4. Both sources.
5. Disconnecting one or both sources from an existing project.
