import logging
import os
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

import dateutil.parser
import dateutil.tz
import requests
from flask import Response
from icalendar import Alarm, Calendar, Event

log = logging.getLogger(__name__)

REQUEST_TIMEOUT = 15  # seconds, per GroupMe API call

# Last good result per group id: {gid: {'name': str|None, 'events': [..], 'fetched_at': datetime}}
# Kept in memory so one flaky GroupMe call doesn't blank out a team's schedule.
_group_cache = {}


def return_ics_Response(response_body):
    return Response(
        response_body,
        mimetype='text/calendar',
        headers={'Content-Disposition': 'attachment'}
    )


def build_ics_urls(ics_url):
    google_calendar_url_base = 'http://www.google.com/calendar/render?cid='
    parsed_ics_url = list(urlparse(ics_url))

    if parsed_ics_url[0] != 'https':
        parsed_ics_url[0] = 'http'
    ics_url_http = urlunparse(parsed_ics_url)

    parsed_ics_url[0] = 'webcal'
    ics_url_webcal = urlunparse(parsed_ics_url)

    parsed_google_url = list(urlparse(google_calendar_url_base))
    parsed_google_url[4] = dict(parse_qsl(parsed_google_url[4]))
    parsed_google_url[4]['cid'] = ics_url_webcal
    parsed_google_url[4] = urlencode(parsed_google_url[4])
    ics_url_google = urlunparse(parsed_google_url)

    return ics_url_http, ics_url_webcal, ics_url_google


def _fetch_group(group_id, headers):
    """Fetch one group's events and name from GroupMe. Raises on any failure."""
    url_calendar = f'https://api.groupme.com/v3/conversations/{group_id}/events/list'
    url_group_info = f'https://api.groupme.com/v3/groups/{group_id}'

    response = requests.get(url_calendar, headers=headers, timeout=REQUEST_TIMEOUT)
    if response.status_code != 200:
        raise RuntimeError(f'events/list returned {response.status_code}: {response.text[:200]}')
    events = response.json().get('response', {}).get('events', [])

    name = None
    try:
        info = requests.get(url_group_info, headers=headers, timeout=REQUEST_TIMEOUT)
        if info.status_code == 200:
            name = info.json().get('response', {}).get('name')
    except requests.RequestException as exc:  # name is cosmetic; keep the events
        log.warning('Group %s: could not fetch group name (%s)', group_id, exc)

    return name, events


def load_groupme_json(app, groupme_api_key, groupme_group_ids):
    """Refresh events for every configured group.

    A group that fails to load keeps its last good data (if any) instead of
    disappearing. Returns True when at least one group loaded live from GroupMe;
    False means nothing could be refreshed (e.g. a bad/expired token).
    Per-group status is stored on app.group_status for the /healthz endpoint.
    """
    headers = {'X-Access-Token': groupme_api_key}
    status = {}
    live_ok = 0

    for group_id in groupme_group_ids:
        try:
            name, events = _fetch_group(group_id, headers)
        except (requests.RequestException, RuntimeError, ValueError) as exc:
            cached = _group_cache.get(group_id)
            if cached:
                log.error('Group %s failed (%s); using data from %s', group_id, exc,
                          cached['fetched_at'].isoformat(timespec='seconds'))
                status[group_id] = 'stale'
            else:
                log.error('Group %s failed (%s); no cached data to fall back on', group_id, exc)
                status[group_id] = 'failed'
            continue

        live_ok += 1
        status[group_id] = 'ok'
        _group_cache[group_id] = {'name': name, 'events': events, 'fetched_at': datetime.now()}

    # Only groups currently configured contribute events; removed IDs fall away.
    for stale_id in set(_group_cache) - set(groupme_group_ids):
        del _group_cache[stale_id]

    combined_events = []
    names = []
    for group_id in groupme_group_ids:
        cached = _group_cache.get(group_id)
        if not cached:
            continue
        if cached['name']:
            names.append(cached['name'])
        for event in cached['events']:
            combined_events.append(dict(event, group_id=group_id, group_name=cached['name']))

    app.groupme_calendar_json_cache = {'response': {'events': combined_events}}
    app.group_status = status
    app.groupme_loaded_names = names
    if live_ok:
        app.last_successful_load = datetime.now()

    return live_ok > 0


def _naive_local(dt, tz_name):
    """Naive datetime in the calendar's timezone, for date-window comparisons only."""
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(dateutil.tz.gettz(tz_name)).replace(tzinfo=None)


def _calendar_name(app):
    static_name = os.environ.get('GROUPME_STATIC_NAME')
    if static_name:
        return static_name
    names = getattr(app, 'groupme_loaded_names', None)
    return ', '.join(names) if names else 'GroupMe Calendar'


def groupme_json_to_ics(groupme_json, app, static_name=None):
    """Build the ICS bytes.

    Events that ended more than GROUPME_LOOKBACK_DAYS (default 14) ago are left
    out, so finished seasons age out on their own without editing group IDs.
    """
    tz_name = app.calendar_timezone
    lookback_days = int(os.environ.get('GROUPME_LOOKBACK_DAYS', 14))
    cutoff = datetime.now() - timedelta(days=lookback_days)
    reminder_minutes = int(os.environ.get('GROUPME_EVENT_REMINDER_MINUTES', 30))
    now_utc = datetime.now(timezone.utc)

    cal = Calendar()
    cal['prodid'] = '-//Andrew Mussey//GroupMe-to-ICS 0.1//EN'
    cal['version'] = '2.0'
    cal['calscale'] = 'GREGORIAN'
    cal['method'] = 'PUBLISH'
    cal['x-wr-calname'] = f'GroupMe: {_calendar_name(app)}'
    cal['x-wr-timezone'] = tz_name
    # Hints for clients that honor them (Outlook mostly sets its own schedule).
    cal['x-published-ttl'] = 'PT1H'

    for json_blob in groupme_json['response']['events']:
        if json_blob.get('deleted_at'):
            continue

        start = dateutil.parser.parse(json_blob['start_at'])
        end = dateutil.parser.parse(json_blob['end_at']) if json_blob.get('end_at') else None
        if _naive_local(end or start, tz_name) < cutoff:
            continue

        event = Event()
        event['uid'] = json_blob['event_id']
        event.add('dtstamp', now_utc)
        event.add('dtstart', start)
        if end:
            event.add('dtend', end)
        group_name = json_blob.get('group_name') or 'GroupMe'
        event['summary'] = f"[{group_name}] {json_blob['name']}"
        description = json_blob.get('description') or ''

        location = json_blob.get('location')
        if location:
            if description:
                description += '\n\nLocation:\n'

            address_clean = (location.get('address') or '').strip().replace('\n', ', ')
            if location.get('name') and location.get('address'):
                event['location'] = f"{location.get('name')}, {address_clean}"
                description += location.get('name') + '\n' + location.get('address')
            elif location.get('name'):
                event['location'] = location.get('name')
                description += location.get('name')
            elif location.get('address'):
                event['location'] = address_clean
                description += location.get('address')

            if location.get('lat') and location.get('lng'):
                location_url = f"https://www.google.com/maps?q={location.get('lat')},{location.get('lng')}"
                if not event.get('location'):
                    event['location'] = location_url
                else:
                    description += '\n' + location_url

        event['description'] = description

        if json_blob.get('updated_at'):
            event.add('last-modified', dateutil.parser.parse(json_blob['updated_at']))

        if reminder_minutes > 0:
            alarm = Alarm()
            alarm.add('action', 'DISPLAY')
            alarm.add('description', 'Reminder')
            alarm.add('trigger', -timedelta(minutes=reminder_minutes))
            event.add_component(alarm)

        cal.add_component(event)

    return cal.to_ical()
