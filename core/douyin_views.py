import json
from urllib.parse import quote

import requests
from django.http import Http404, HttpResponse, JsonResponse, StreamingHttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from .douyin_monitor import USER_AGENT, monitor_manager, serialize_monitor
from .douyin_report import create_interactive_report
from .models import DouyinMonitorSession


def response_json(data, status=200):
    return JsonResponse(data, status=status, json_dumps_params={'ensure_ascii': False})


def request_payload(request):
    try:
        return json.loads(request.body.decode('utf-8')) if request.body else {}
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}


@require_GET
def monitor_health(_request):
    return response_json({
        'ok': True,
        'service': 'creator-douyin-live-monitor',
        'version': '1.5.0-web',
        'storage': 'local-django-sqlite',
    })


@require_GET
def monitor_state(_request):
    return response_json(monitor_manager.state())


@csrf_exempt
@require_POST
def start_monitor(request):
    ok, message, session = monitor_manager.start(request_payload(request).get('douyinId'))
    if not ok:
        return response_json({'ok': False, 'message': message}, status=400)
    return response_json({'ok': True, 'monitor': serialize_monitor(session)}, status=201)


@csrf_exempt
@require_POST
def stop_monitor(_request, session_id):
    ok, message = monitor_manager.stop(session_id)
    return response_json({'ok': ok, 'message': message}, status=200 if ok else 409)


@csrf_exempt
@require_POST
def refresh_monitor_stream(_request, session_id):
    ok, message = monitor_manager.refresh_stream(session_id)
    return response_json({'ok': ok, 'message': message}, status=200 if ok else 409)


@csrf_exempt
@require_http_methods(['POST', 'PUT'])
def save_monitor_config(request, session_id):
    ok, message, session = monitor_manager.save_config(session_id, request_payload(request))
    if not ok:
        return response_json({'ok': False, 'message': message}, status=400)
    return response_json({'ok': True, 'monitor': serialize_monitor(session)})


@csrf_exempt
@require_http_methods(['DELETE'])
def delete_monitor_log(_request, session_id):
    ok, message = monitor_manager.delete_log(session_id)
    return response_json({'ok': ok, 'message': message}, status=200 if ok else 409)


@require_GET
def export_monitor_log(_request, session_id):
    session = DouyinMonitorSession.objects.filter(id=session_id).first()
    if not session:
        raise Http404('Monitor log not found.')
    if not session.points:
        return response_json({'ok': False, 'message': '当前日志还没有可导出的在线人数数据'}, status=409)
    safe_id = ''.join('_' if char in '\\/:*?"<>|' else char for char in (session.douyin_id or '直播间'))
    stamp = session.started_at.astimezone().strftime('%Y%m%d-%H%M')
    filename = f'{safe_id}_实时人数曲线_{stamp}.html'
    response = HttpResponse(create_interactive_report(session), content_type='text/html; charset=utf-8')
    response['Content-Disposition'] = f"attachment; filename*=UTF-8''{quote(filename)}"
    return response


@require_GET
def monitor_stream(request, session_id):
    session = DouyinMonitorSession.objects.filter(id=session_id, ended_at__isnull=True).first()
    if not session or not session.stream_url:
        raise Http404('Monitor stream is not ready.')
    headers = {
        'User-Agent': USER_AGENT,
        'Referer': f'https://live.douyin.com/{session.web_rid}',
    }
    if request.headers.get('Range'):
        headers['Range'] = request.headers['Range']
    try:
        upstream = requests.get(session.stream_url, headers=headers, stream=True, timeout=(12, 30))
        upstream.raise_for_status()
    except requests.RequestException as exc:
        return response_json({'ok': False, 'message': f'直播视频流连接失败：{exc}'}, status=502)

    def chunks():
        try:
            yield from upstream.iter_content(chunk_size=64 * 1024)
        finally:
            upstream.close()

    response = StreamingHttpResponse(
        chunks(),
        status=upstream.status_code,
        content_type=upstream.headers.get('Content-Type', 'video/x-flv'),
    )
    response['Cache-Control'] = 'no-store'
    response['X-Accel-Buffering'] = 'no'
    for name in ('Content-Length', 'Content-Range', 'Accept-Ranges'):
        if upstream.headers.get(name):
            response[name] = upstream.headers[name]
    return response
