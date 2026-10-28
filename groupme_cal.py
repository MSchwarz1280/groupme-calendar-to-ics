import datetime
import hmac
import os

from flask import Flask, Response, abort, current_app, jsonify, render_template, request
from werkzeug.middleware.proxy_fix import ProxyFix

import utils

app = Flask(__name__)
# Render terminates TLS in front of gunicorn; trust its forwarded headers so
# generated links use https and the real hostname.
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

with app.app_context():
    current_app.calendar_timezone = os.environ.get('GROUPME_CALENDAR_TIMEZONE', 'America/New_York')

RETRY_AFTER_FAILURE = datetime.timedelta(seconds=60)


def _group_ids():
    raw = os.environ.get('GROUPME_GROUP_ID', '')
    return raw, [gid.strip() for gid in raw.split(',') if gid.strip()]


def _check_key():
    """Optional shared secret: if CALENDAR_SECRET is set, ?key=... must match."""
    secret = os.environ.get('CALENDAR_SECRET')
    if secret and not hmac.compare_digest(request.args.get('key', ''), secret):
        abort(404)


def refresh_cache():
    """Make sure app.ics_cache is as fresh as the cache duration allows.

    Returns None on success (or when a stale copy is being served), or an
    error string when there is nothing at all to serve.
    A failed refresh never replaces the last good calendar with an empty one.
    """
    raw_ids, group_ids = _group_ids()
    if not group_ids:
        return 'GROUPME_GROUP_ID is not set'
    api_key = os.environ.get('GROUPME_API_KEY')
    if not api_key:
        return 'GROUPME_API_KEY is not set'

    now = datetime.datetime.now()
    cache_duration = int(os.environ.get('CACHE_DURATION', 60))
    last_cache = getattr(app, 'last_cache', None)
    retry_at = getattr(app, 'retry_at', None)
    have_cache = getattr(app, 'ics_cache', None) is not None

    fresh = (
        have_cache and last_cache is not None and cache_duration != 0
        and now - last_cache <= datetime.timedelta(minutes=cache_duration)
    )
    if fresh:
        print(f'Cache hit. Time remaining: {datetime.timedelta(minutes=cache_duration) - (now - last_cache)}')
        return None
    if retry_at and now < retry_at and have_cache:
        return None  # recently failed; keep serving the last good copy

    print('Cache miss.')
    if utils.load_groupme_json(app=app, groupme_api_key=api_key, groupme_group_ids=group_ids):
        app.ics_cache = utils.groupme_json_to_ics(app.groupme_calendar_json_cache, app)
        app.last_cache = now
        app.retry_at = None
        return None

    app.retry_at = now + RETRY_AFTER_FAILURE
    if have_cache:
        app.logger.error('Refresh failed; serving the last good calendar.')
        return None
    return 'Could not load any group from GroupMe (check GROUPME_API_KEY and the group IDs)'


@app.route('/')
def index():
    _check_key()
    raw_ids, _ = _group_ids()
    error = refresh_cache()
    if error:
        return Response(f'ERROR: {error}', status=503, mimetype='text/plain')

    ics_url = os.environ.get('GROUPME_PROXY_URL', request.url_root + 'calendar.ics')
    secret = os.environ.get('CALENDAR_SECRET')
    if secret and 'GROUPME_PROXY_URL' not in os.environ:
        ics_url += f'?key={secret}'

    ics_url_http, ics_url_webcal, ics_url_google = utils.build_ics_urls(ics_url)
    return render_template(
        'index.html',
        title=utils._calendar_name(app),
        groupme_id=raw_ids,
        ics_url_http=ics_url_http,
        ics_url_webcal=ics_url_webcal,
        ics_url_google=ics_url_google,
        calendar_timezone=app.calendar_timezone,
    )


@app.route('/calendar.ics')
def full_ics():
    _check_key()
    error = refresh_cache()
    if error:
        # 503 (not an empty calendar) so subscribers keep their existing events.
        return Response(f'ERROR: {error}', status=503, mimetype='text/plain')
    return utils.return_ics_Response(app.ics_cache)


@app.route('/healthz')
def healthz():
    """Cheap status check that never calls GroupMe. Safe for Render's health check."""
    status = getattr(app, 'group_status', {})
    last_ok = getattr(app, 'last_successful_load', None)
    return jsonify(
        status='ok' if getattr(app, 'ics_cache', None) is not None or not status else 'degraded',
        groups_configured=len(_group_ids()[1]),
        groups_ok=sum(1 for s in status.values() if s == 'ok'),
        groups_stale=sum(1 for s in status.values() if s == 'stale'),
        groups_failed=sum(1 for s in status.values() if s == 'failed'),
        last_successful_load=last_ok.isoformat(timespec='seconds') if last_ok else None,
    )


@app.route('/robots.txt')
def robots():
    return 'User-agent: *\nDisallow: /'


if __name__ == "__main__":
    app.run(debug=True)
