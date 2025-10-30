from flask import Flask, current_app, render_template, request
import os
import datetime
import utils

app = Flask(__name__)

with app.app_context():
    current_app.calendar_timezone = os.environ.get('GROUPME_CALENDAR_TIMEZONE', 'America/Los_Angeles')
    current_app.groupme_calendar_name = os.environ.get('GROUPME_STATIC_NAME', 'GroupMe Calendar')

@app.route('/')
def index():
    last_cache = getattr(current_app, 'last_cache', datetime.datetime(year=2000, month=1, day=1))
    cache_duration = int(os.environ.get('CACHE_DURATION', 60))
    groupme_group_ids = os.environ.get('GROUPME_GROUP_IDS', None)

    if not groupme_group_ids:
        return 'ERROR: The GROUPME_GROUP_IDS is not set.'

    if datetime.datetime.now() - last_cache > datetime.timedelta(minutes=cache_duration) or cache_duration == 0:
        print('Cache miss.')
        groupme_api_key = os.environ.get('GROUPME_API_KEY', None)
        if not groupme_api_key:
            return 'ERROR: The GROUPME_API_KEY is not set.'

        combined_json = []
        for group_id in groupme_group_ids.split(','):
            group_id = group_id.strip()
            success = utils.load_groupme_json(app=app, groupme_api_key=groupme_api_key, groupme_group_id=group_id)
            if not success:
                return f'Error loading calendar for group ID {group_id}.'
            combined_json.extend(current_app.groupme_calendar_json_cache)

        current_app.ics_cache = utils.groupme_json_to_ics(groupme_json=combined_json)
        current_app.last_cache = datetime.datetime.now()
    else:
        print('Cache hit. Time remaining: {}'.format(datetime.timedelta(minutes=cache_duration) - (datetime.datetime.now() - last_cache)))

    ics_url = os.environ.get('GROUPME_PROXY_URL', request.url + 'calendar.ics')
    if request.url[-1] == '/':
        ics_url = request.url + 'calendar.ics'

    ics_url_http, ics_url_webcal, ics_url_google = utils.build_ics_urls(ics_url)
    params = {
        'title': current_app.groupme_calendar_name,
        'groupme_id': groupme_group_ids,
        'ics_url_http': ics_url_http,
        'ics_url_webcal': ics_url_webcal,
        'ics_url_google': ics_url_google,
        'calendar_timezone': current_app.calendar_timezone,
    }
    return render_template('index.html', **params)

@app.route('/calendar.ics')
def full_ics():
    last_cache = getattr(current_app, 'last_cache', datetime.datetime(year=2000, month=1, day=1))
    cache_duration = int(os.environ.get('CACHE_DURATION', 60))
    groupme_group_ids = os.environ.get('GROUPME_GROUP_IDS', None)

    if datetime.datetime.now() - last_cache > datetime.timedelta(minutes=cache_duration) or cache_duration == 0:
        print('Cache miss.')
        groupme_api_key = os.environ.get('GROUPME_API_KEY', None)
        if not groupme_api_key:
            return utils.return_ics_Response(utils.groupme_ics_error(error_text='GROUPME_API_KEY not set'))
        if not groupme_group_ids:
            return utils.return_ics_Response(utils.groupme_ics_error(error_text='GROUPME_GROUP_IDS not set'))

        combined_json = []
        for group_id in groupme_group_ids.split(','):
            group_id = group_id.strip()
            success = utils.load_groupme_json(app=app, groupme_api_key=groupme_api_key, groupme_group_id=group_id)
            if not success:
                return utils.return_ics_Response(utils.groupme_ics_error(error_text=f'Error loading calendar for group ID {group_id}'))
            combined_json.extend(current_app.groupme_calendar_json_cache)

        current_app.ics_cache = utils.groupme_json_to_ics(groupme_json=combined_json)
        current_app.last_cache = datetime.datetime.now()
    else:
        print('Cache hit. Time remaining: {}'.format(datetime.timedelta(minutes=cache_duration) - (datetime.datetime.now() - last_cache)))

    return utils.return_ics_Response(getattr(current_app, 'ics_cache', None))

@app.route('/recent.ics')
def recent_ics():
    return 'Soon!'

@app.route('/robots.txt')
def robots():
    return 'User-agent: *\nDisallow: /'

if __name__ == "__main__":
    app.run(debug=True)