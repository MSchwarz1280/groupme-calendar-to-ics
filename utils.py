from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode
from icalendar import Calendar, Event
from flask import Response, current_app
import dateutil.parser
import requests

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

def load_groupme_json(app, groupme_api_key, groupme_group_ids):
    combined_events = []
    calendar_names = []

    for group_id in groupme_group_ids:
        url_group_info = f'https://api.groupme.com/v3/groups/{group_id}'
        url_calendar = f'https://api.groupme.com/v3/conversations/{group_id}/events/list'
        headers = {'X-Access-Token': groupme_api_key}

        response = requests.get(url_calendar, headers=headers)
        if response.status_code != 200:
            app.logger.error(f'{response.status_code}: {response.text}')
            continue

        group_events = response.json().get('response', {}).get('events', [])

        response_info = requests.get(url_group_info, headers=headers)
        group_name = None
        if response_info.status_code == 200:
            group_name = response_info.json().get('response', {}).get('name', None)
            if group_name:
                calendar_names.append(group_name)

        for event in group_events:
            event['group_id'] = group_id
            event['group_name'] = group_name
            combined_events.append(event)

    current_app.groupme_calendar_json_cache = {'response': {'events': combined_events}}
    current_app.groupme_calendar_name = ', '.join(calendar_names) if calendar_names else 'GroupMe Calendar'
    current_app.groupme_load_successfully = True

    return bool(combined_events)

def groupme_json_to_ics(groupme_json, static_name=None):
    cal = Calendar()
    cal['prodid'] = '-//Andrew Mussey//GroupMe-to-ICS 0.1//EN'
    cal['version'] = '2.0'
    cal['calscale'] = 'GREGORIAN'
    cal['method'] = 'PUBLISH'
    cal['x-wr-calname'] = f'GroupMe: {current_app.groupme_calendar_name}'
    cal['x-wr-timezone'] = current_app.calendar_timezone

    for json_blob in groupme_json['response']['events']:
        if 'deleted_at' not in json_blob:
            event = Event()
            event['uid'] = json_blob['event_id']
            event.add('dtstart', dateutil.parser.parse(json_blob['start_at']))
            if json_blob.get('end_at'):
                event.add('dtend', dateutil.parser.parse(json_blob['end_at']))
            group_name = json_blob.get('group_name', 'GroupMe')
            event['summary'] = f"[{group_name}] {json_blob['name']}"
            event['description'] = json_blob.get('description', '')

            if json_blob.get('location'):
                location = json_blob.get('location', {})
                if json_blob.get('description'):
                    event['description'] += '\n\nLocation:\n'

                address_clean = location.get('address', '').strip().replace('\n', ', ')
                if location.get('name') and location.get('address'):
                    event['location'] = f"{location.get('name')}, {address_clean}"
                    event['description'] += location.get('name') + '\n' + location.get('address')
                elif location.get('name'):
                    event['location'] = location.get('name')
                    event['description'] += location.get('name')
                elif location.get('address'):
                    event['location'] = address_clean
                    event['description'] += location.get('address')

                if location.get('lat') and location.get('lng'):
                    location_url = f"https://www.google.com/maps?q={location.get('lat')},{location.get('lng')}"
                    if not event.get('location'):
                        event['location'] = location_url
                    else:
                        event['description'] += '\n' + location_url

            if json_blob.get('updated_at'):
                event['last-modified'] = dateutil.parser.parse(json_blob.get('updated_at'))

            cal.add_component(event)

    return cal.to_ical()

def groupme_ics_error(error_text, static_name=None):
    cal = Calendar()
    cal['prodid'] = '-//Andrew Mussey//GroupMe-to-ICS 0.1//EN'
    cal['version'] = '2.0'
    cal['calscale'] = 'GREGORIAN'
    cal['method'] = 'PUBLISH'
    cal['x-wr-calname'] = f'GroupMe: {current_app.groupme_calendar_name} ({error_text})'
    cal['x-wr-timezone'] = current_app.calendar_timezone
    return cal.to_ical()