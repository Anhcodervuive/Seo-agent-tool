from google.oauth2 import service_account
from googleapiclient.discovery import build

import os
BASE = os.path.dirname(os.path.abspath(__file__))
KEY = os.path.join(os.path.dirname(BASE), "credentials", "google-service-account.json")
SITE = 'sc-domain:infozzle.com'

creds = service_account.Credentials.from_service_account_file(
    KEY, scopes=['https://www.googleapis.com/auth/webmasters.readonly'])
service = build('searchconsole', 'v1', credentials=creds)

resp = service.searchanalytics().query(
    siteUrl=SITE,
    body={
        'startDate': '2026-06-01',
        'endDate': '2026-06-28',
        'dimensions': ['query'],
        'rowLimit': 5,
    }).execute()

print('GSC connection works. Top queries for Infozzle:')
for row in resp.get('rows', []):
    print(f"  {row['keys'][0]} | clicks: {row['clicks']} | impressions: {row['impressions']} | pos: {row['position']:.1f}")
if not resp.get('rows'):
    print('  (connected, but no query data in this date range)')
