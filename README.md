# GroupMe Calendar to ICS

Combines the event calendars of several GroupMe groups into one ICS feed you can
subscribe to from Outlook, Google Calendar or Apple Calendar. Forked from
amussey/groupme-calendar-to-ics and adapted to handle multiple groups.

Feed URL: `https://<your-service>.onrender.com/calendar.ics`

## Environment variables (set in the Render dashboard)

| Variable | Purpose |
|---|---|
| `GROUPME_API_KEY` | **Required.** Access token from https://dev.groupme.com (top right). If the feed stops updating and the Render log shows `401 unauthorized`, this token needs replacing. |
| `GROUPME_GROUP_ID` | **Required.** Comma-separated group IDs. |
| `GROUPME_CALENDAR_TIMEZONE` | Default `America/New_York`. |
| `GROUPME_LOOKBACK_DAYS` | Default `14`. Events that ended longer ago than this are left out of the feed, so finished seasons drop off on their own. You can leave old group IDs in place, or remove them whenever convenient. |
| `GROUPME_EVENT_REMINDER_MINUTES` | Default `30`. `0` turns reminders off. |
| `CACHE_DURATION` | Minutes to cache GroupMe data. Default `60`. |
| `GROUPME_STATIC_NAME` | Optional fixed calendar name (otherwise the group names are joined). |
| `CALENDAR_SECRET` | Optional. If set, the feed and home page need `?key=<secret>`. Subscribe with `.../calendar.ics?key=<secret>`. Without it, anyone with the URL can read your schedules. |
| `GROUPME_PROXY_URL` | Optional URL to show on the home page instead of the detected one. |

## Behavior worth knowing

* A group that fails to load keeps its last good events. If everything fails after a good load, the last good calendar is served.
* If nothing has ever loaded, `/calendar.ics` returns HTTP 503 rather than an empty calendar, so subscribers don't lose events.
* `/healthz` reports per-group status counts without calling GroupMe. Details are in the Render logs.
* The cache is in memory. Render's free tier sleeps idle services, so the first request after a sleep re-fetches.

## Adding to Outlook (Microsoft 365)

Outlook on the web: Add calendar > Subscribe from web > paste the feed URL. Outlook refreshes subscribed calendars on its own schedule (often several hours) and the calendar is read-only. Your IT policy may restrict internet calendar subscriptions.

## Local development and tests

    pip install -r requirements.txt pytest
    python -m pytest test_feed.py
