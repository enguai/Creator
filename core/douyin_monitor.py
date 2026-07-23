import base64
import hashlib
import hmac
import json
import re
import threading
import time
from dataclasses import dataclass
from datetime import timedelta
from urllib.parse import urlencode, urlparse

import requests
from django.db import close_old_connections
from django.utils import timezone

from .models import DouyinMonitorConfig, DouyinMonitorSession


USER_AGENT = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
    'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36'
)
CURVE_SAMPLE_INTERVAL_MS = 5 * 60 * 1000
ACTIVE_STATUSES = {
    DouyinMonitorSession.Status.STARTING,
    DouyinMonitorSession.Status.RESOLVING,
    DouyinMonitorSession.Status.CONNECTING,
    DouyinMonitorSession.Status.MONITORING,
    DouyinMonitorSession.Status.WARNING,
    DouyinMonitorSession.Status.ERROR,
}


def timestamp_ms(value):
    return int(value.timestamp() * 1000) if value else None


def default_config():
    return {
        'enabled': False,
        'mode': 'greater',
        'threshold': 100,
        'min': 50,
        'max': 100,
        'cooldownEnabled': False,
        'cooldownMinutes': 10,
        'webhook': '',
        'secret': '',
    }


def config_payload(config):
    if not config:
        return default_config()
    return {
        'enabled': config.enabled,
        'mode': config.mode,
        'threshold': config.threshold,
        'min': config.min_count,
        'max': config.max_count,
        'cooldownEnabled': config.cooldown_enabled,
        'cooldownMinutes': config.cooldown_minutes,
        'webhook': config.webhook,
        'secret': config.secret,
    }


def normalize_config(value):
    source = value if isinstance(value, dict) else {}

    def nonnegative_int(name, default):
        try:
            return max(0, int(source.get(name, default)))
        except (TypeError, ValueError):
            return default

    mode = source.get('mode') if source.get('mode') in {'greater', 'less', 'range'} else 'greater'
    cooldown_minutes = nonnegative_int('cooldownMinutes', 10) or 10
    return {
        'enabled': bool(source.get('enabled')),
        'mode': mode,
        'threshold': nonnegative_int('threshold', 100),
        'min': nonnegative_int('min', 50),
        'max': nonnegative_int('max', 100),
        'cooldownEnabled': bool(source.get('cooldownEnabled')),
        'cooldownMinutes': cooldown_minutes,
        'webhook': str(source.get('webhook') or '').strip(),
        'secret': str(source.get('secret') or '').strip(),
    }


def validate_config(value):
    config = normalize_config(value)
    if config['mode'] == 'range' and config['min'] > config['max']:
        return False, '区间最小值不能大于最大值', config
    if config['enabled']:
        parsed = urlparse(config['webhook'])
        if parsed.scheme != 'https' or not parsed.netloc:
            return False, '开启飞书告警前，请填写有效的 HTTPS Webhook 地址', config
    return True, '', config


def matches_rule(count, config):
    if config.get('mode') == 'less':
        return count < config.get('threshold', 100)
    if config.get('mode') == 'range':
        return config.get('min', 50) <= count <= config.get('max', 100)
    return count > config.get('threshold', 100)


def parse_compact_number(value):
    text = str(value or '').replace(',', '').strip()
    match = re.fullmatch(r'(\d+(?:\.\d+)?)\s*([万亿wW])?', text)
    if not match:
        return None
    number = float(match.group(1))
    if match.group(2) in {'万', 'w', 'W'}:
        number *= 10000
    elif match.group(2) == '亿':
        number *= 100000000
    return round(number)


def serialize_monitor(session):
    return {
        'id': str(session.id),
        'douyinId': session.douyin_id,
        'roomTitle': session.room_title,
        'startedAt': timestamp_ms(session.started_at),
        'status': session.status,
        'statusMessage': session.status_message,
        'currentCount': session.current_count,
        'points': session.points[-7200:],
        'alerts': session.alerts,
        'config': session.config or default_config(),
        'videoReady': bool(session.stream_url),
        'streamUrl': f'/api/live-monitor/monitors/{session.id}/stream/' if session.stream_url else '',
    }


def serialize_log(session):
    return {
        **serialize_monitor(session),
        'endedAt': timestamp_ms(session.ended_at),
        'endReason': session.end_reason,
    }


def normalize_douyin_input(value):
    return re.sub(r'\s+', ' ', str(value or '').strip().lstrip('@'))


@dataclass
class MonitorRuntime:
    stop_event: threading.Event
    http: requests.Session
    thread: threading.Thread | None = None


class DouyinMonitorManager:
    def __init__(self):
        self._lock = threading.RLock()
        self._runtimes = {}
        self._initialized = False

    def ensure_initialized(self):
        with self._lock:
            if self._initialized:
                return
            now = timezone.now()
            stale = DouyinMonitorSession.objects.filter(
                ended_at__isnull=True,
                status__in=[
                    DouyinMonitorSession.Status.STARTING,
                    DouyinMonitorSession.Status.RESOLVING,
                    DouyinMonitorSession.Status.CONNECTING,
                    DouyinMonitorSession.Status.MONITORING,
                    DouyinMonitorSession.Status.WARNING,
                ],
            )
            stale.update(
                status=DouyinMonitorSession.Status.STOPPED,
                status_message='本地监控服务已重新启动',
                ended_at=now,
                end_reason='本地监控服务重启',
                updated_at=now,
            )
            self._initialized = True

    def state(self):
        self.ensure_initialized()
        monitors = DouyinMonitorSession.objects.filter(ended_at__isnull=True).order_by('started_at')
        logs = DouyinMonitorSession.objects.all().order_by('-started_at')[:300]
        return {
            'monitors': [serialize_monitor(item) for item in monitors],
            'logs': [serialize_log(item) for item in logs],
        }

    def start(self, value):
        self.ensure_initialized()
        douyin_id = normalize_douyin_input(value)
        if not douyin_id:
            return False, '请输入抖音号', None
        if len(douyin_id) > 120:
            return False, '输入内容过长', None
        if douyin_id.lower().startswith('javascript:'):
            return False, '请输入有效的抖音号', None

        saved_config = DouyinMonitorConfig.objects.filter(douyin_id=douyin_id).first()
        session = DouyinMonitorSession.objects.create(
            douyin_id=douyin_id,
            config=config_payload(saved_config),
        )
        http = requests.Session()
        http.headers.update({'User-Agent': USER_AGENT, 'Accept': 'application/json, text/plain, */*'})
        runtime = MonitorRuntime(stop_event=threading.Event(), http=http)
        thread = threading.Thread(
            target=self._run_monitor,
            args=(session.id, runtime),
            name=f'douyin-monitor-{session.id}',
            daemon=True,
        )
        runtime.thread = thread
        with self._lock:
            self._runtimes[str(session.id)] = runtime
        thread.start()
        return True, '', session

    def stop(self, session_id, reason='用户停止监控'):
        self.ensure_initialized()
        try:
            session = DouyinMonitorSession.objects.get(id=session_id)
        except DouyinMonitorSession.DoesNotExist:
            return False, '监控任务不存在或已删除'
        if session.ended_at:
            return False, '监控任务已经停止'
        with self._lock:
            runtime = self._runtimes.get(str(session.id))
            if runtime:
                runtime.stop_event.set()
        self._finish_session(session.id, reason)
        return True, ''

    def save_config(self, session_id, value):
        self.ensure_initialized()
        ok, message, config = validate_config(value)
        if not ok:
            return False, message, None
        try:
            session = DouyinMonitorSession.objects.get(id=session_id, ended_at__isnull=True)
        except DouyinMonitorSession.DoesNotExist:
            return False, '监控任务不存在或已经停止', None
        DouyinMonitorConfig.objects.update_or_create(
            douyin_id=session.douyin_id,
            defaults={
                'enabled': config['enabled'],
                'mode': config['mode'],
                'threshold': config['threshold'],
                'min_count': config['min'],
                'max_count': config['max'],
                'cooldown_enabled': config['cooldownEnabled'],
                'cooldown_minutes': config['cooldownMinutes'],
                'webhook': config['webhook'],
                'secret': config['secret'],
            },
        )
        session.config = config
        session.save(update_fields=['config', 'updated_at'])
        return True, '', session

    def refresh_stream(self, session_id):
        self.ensure_initialized()
        try:
            session = DouyinMonitorSession.objects.get(id=session_id, ended_at__isnull=True)
        except DouyinMonitorSession.DoesNotExist:
            return False, '监控任务不存在或已经停止'
        with self._lock:
            runtime = self._runtimes.get(str(session.id))
        if not runtime or not session.sec_uid:
            return False, '直播间连接尚未就绪'
        try:
            profile, room_id = self._fetch_profile(runtime.http, session.sec_uid)
            room_data = self._parse_room_data(profile.get('user', {}).get('room_data'))
            stream_url = self._choose_stream_url(room_data)
            if not stream_url:
                raise RuntimeError('暂时无法取得直播视频流')
            session.stream_url = stream_url
            session.room_id = room_id or session.room_id
            session.save(update_fields=['stream_url', 'room_id', 'updated_at'])
            return True, ''
        except Exception as exc:
            return False, str(exc) or '刷新直播画面失败'

    def delete_log(self, session_id):
        self.ensure_initialized()
        try:
            session = DouyinMonitorSession.objects.get(id=session_id)
        except DouyinMonitorSession.DoesNotExist:
            return False, '日志不存在或已删除'
        if not session.ended_at:
            return False, '请先停止监控，再删除日志'
        session.delete()
        return True, ''

    def _set_status(self, session_id, status, message, **extra):
        values = {'status': status, 'status_message': str(message)[:300], 'updated_at': timezone.now(), **extra}
        DouyinMonitorSession.objects.filter(id=session_id, ended_at__isnull=True).update(**values)

    def _run_monitor(self, session_id, runtime):
        close_old_connections()
        try:
            self._resolve(session_id, runtime)
            while not runtime.stop_event.wait(1):
                session = DouyinMonitorSession.objects.filter(id=session_id, ended_at__isnull=True).first()
                if not session or not session.web_rid:
                    break
                self._poll_viewer_count(session, runtime)
        except Exception as exc:
            self._set_status(session_id, DouyinMonitorSession.Status.ERROR, str(exc) or '连接抖音直播间失败')
        finally:
            runtime.http.close()
            with self._lock:
                self._runtimes.pop(str(session_id), None)
            close_old_connections()

    def _resolve(self, session_id, runtime):
        session = DouyinMonitorSession.objects.get(id=session_id)
        self._set_status(session_id, DouyinMonitorSession.Status.RESOLVING, '正在匿名识别抖音号')
        runtime.http.get('https://live.douyin.com/', timeout=12)
        sec_uid = self._resolve_sec_uid(runtime.http, session.douyin_id)
        profile, room_id = self._fetch_profile(runtime.http, sec_uid)
        user = profile.get('user') or {}
        room_data = self._parse_room_data(user.get('room_data'))
        if int(user.get('live_status') or 0) != 1 or not (room_data or {}).get('owner', {}).get('web_rid'):
            raise RuntimeError('该账号当前未开播')
        stream_url = self._choose_stream_url(room_data)
        if not stream_url:
            raise RuntimeError('直播间暂未提供可播放的视频流')
        self._set_status(
            session_id,
            DouyinMonitorSession.Status.MONITORING,
            '匿名直播画面已连接',
            sec_uid=sec_uid,
            room_title=str(user.get('nickname') or session.douyin_id)[:200],
            room_id=str(room_id or room_data.get('id_str') or room_data.get('id') or user.get('room_id') or ''),
            web_rid=str(room_data['owner']['web_rid']),
            stream_url=stream_url,
        )
        session.refresh_from_db()
        self._poll_viewer_count(session, runtime)

    def _resolve_sec_uid(self, http, value):
        try:
            parsed = urlparse(value)
            if parsed.hostname == 'live.douyin.com' and re.match(r'^/\d+', parsed.path):
                response = http.get(value, timeout=12)
                response.raise_for_status()
                match = re.search(r'\\?"owner\\?"\s*:\s*\{[\s\S]{0,2500}?\\?"sec_uid\\?"\s*:\s*\\?"([^"\\]+)\\?"', response.text)
                if not match:
                    raise RuntimeError('无法从直播链接识别主播账号')
                return match.group(1)
        except ValueError:
            pass

        query = urlencode({
            'device_platform': 'webapp',
            'aid': '6383',
            'channel': 'channel_pc_web',
            'keyword': value,
            'source': 'aweme_video_web',
        })
        response = http.get(
            f'https://www.douyin.com/aweme/v1/web/search/sug/?{query}',
            headers={'Referer': f'https://www.douyin.com/search/{value}?type=user'},
            timeout=12,
        )
        response.raise_for_status()
        candidates = response.json().get('sug_list') or []
        normalized = value.lower()
        for item in candidates:
            info = item.get('extra_info') or {}
            if any(str(candidate or '').lower() == normalized for candidate in (info.get('rich_sug_short_id'), item.get('content'))):
                sec_uid = info.get('rich_sug_sec_uid')
                if sec_uid:
                    return sec_uid
        raise RuntimeError('没有找到该抖音号，请检查输入是否正确')

    def _fetch_profile(self, http, sec_uid):
        query = urlencode({
            'device_platform': 'webapp',
            'aid': '6383',
            'channel': 'channel_pc_web',
            'sec_user_id': sec_uid,
            '_': int(time.time() * 1000),
        })
        response = http.get(
            f'https://www.douyin.com/aweme/v1/web/user/profile/other/?{query}',
            headers={'Referer': f'https://www.douyin.com/user/{sec_uid}'},
            timeout=12,
        )
        response.raise_for_status()
        room_match = re.search(r'"room_id"\s*:\s*(?:"(\d+)"|(\d+))', response.text)
        room_id = (room_match.group(1) or room_match.group(2)) if room_match else ''
        return response.json(), room_id

    @staticmethod
    def _parse_room_data(value):
        if isinstance(value, dict):
            return value
        try:
            return json.loads(value) if value else None
        except (TypeError, json.JSONDecodeError):
            return None

    @staticmethod
    def _choose_stream_url(room_data):
        urls = (room_data or {}).get('stream_url', {}).get('flv_pull_url', {})
        for key in ('HD1', 'SD2', 'SD1', 'FULL_HD1'):
            if urls.get(key):
                return str(urls[key]).replace('http:', 'https:', 1)
        return str(next(iter(urls.values()), '')).replace('http:', 'https:', 1)

    def _poll_viewer_count(self, session, runtime):
        query = urlencode({
            'aid': '6383',
            'app_name': 'douyin_web',
            'live_id': '1',
            'device_platform': 'web',
            'language': 'zh-CN',
            'enter_from': 'web_live',
            'cookie_enabled': 'true',
            'screen_width': '1920',
            'screen_height': '1080',
            'browser_language': 'zh-CN',
            'browser_platform': 'Win32',
            'browser_name': 'Chrome',
            'browser_version': '138.0.0.0',
            'web_rid': session.web_rid,
            'room_id_str': session.room_id,
            '_': int(time.time() * 1000),
        })
        try:
            response = runtime.http.get(
                f'https://live.douyin.com/webcast/room/web/enter/?{query}',
                headers={'Referer': f'https://live.douyin.com/{session.web_rid}'},
                timeout=12,
            )
            response.raise_for_status()
            data = response.json().get('data') or {}
            if data.get('room_status') is not None and int(data['room_status']) != 0:
                self._set_status(session.id, DouyinMonitorSession.Status.ERROR, '直播已经结束')
                runtime.stop_event.set()
                return
            room = (data.get('data') or [{}])[0]
            stats = room.get('room_view_stats') or {}
            count = parse_compact_number(stats.get('display_value') or stats.get('display_short_anchor'))
            if count is not None and count >= 0:
                self._record_count(session.id, count)
        except Exception as exc:
            failures = getattr(runtime, 'poll_failures', 0) + 1
            runtime.poll_failures = failures
            if failures >= 5:
                self._set_status(session.id, DouyinMonitorSession.Status.WARNING, f'在线人数读取重试中：{exc}')

    def _record_count(self, session_id, count):
        session = DouyinMonitorSession.objects.get(id=session_id, ended_at__isnull=True)
        previous = session.current_count
        now_ms = int(time.time() * 1000)
        started_ms = timestamp_ms(session.started_at)
        points = list(session.points or [])
        current_slot = max(0, (now_ms - started_ms) // CURVE_SAMPLE_INTERVAL_MS)
        last_slot = -1
        if points:
            last_slot = (int(points[-1]['time']) - started_ms) // CURVE_SAMPLE_INTERVAL_MS
        if not points or current_slot > last_slot:
            points.append({'time': started_ms + current_slot * CURVE_SAMPLE_INTERVAL_MS, 'count': count})
            points = points[-10000:]
        session.current_count = count
        session.points = points
        session.status = DouyinMonitorSession.Status.MONITORING
        session.status_message = '匿名直播画面已连接'
        session.save(update_fields=['current_count', 'points', 'status', 'status_message', 'updated_at'])
        if previous != count:
            self._evaluate_alert(session)

    def _evaluate_alert(self, session):
        config = session.config or default_config()
        if not config.get('enabled') or not config.get('webhook') or not matches_rule(session.current_count, config):
            return
        now = timezone.now()
        if config.get('cooldownEnabled') and session.last_alert_at:
            if now - session.last_alert_at < timedelta(minutes=config.get('cooldownMinutes', 10)):
                return
        event = {'time': timestamp_ms(now), 'count': session.current_count, 'status': 'sending'}
        alerts = list(session.alerts or [])
        alerts.append(event)
        session.alerts = alerts
        session.last_alert_at = now
        session.save(update_fields=['alerts', 'last_alert_at', 'updated_at'])
        text = f'直播间：{session.room_title or "未获取"}\n抖音号：{session.douyin_id}\n当前实时在线人数：{session.current_count}人'
        payload = {'msg_type': 'text', 'content': {'text': text}}
        if config.get('secret'):
            timestamp = str(int(now.timestamp()))
            key = f'{timestamp}\n{config["secret"]}'.encode()
            payload.update({
                'timestamp': timestamp,
                'sign': base64.b64encode(hmac.new(key, b'', hashlib.sha256).digest()).decode(),
            })
        try:
            response = requests.post(config['webhook'], json=payload, timeout=12)
            result = response.json() if response.content else {}
            if not response.ok or result.get('code', 0) != 0 or result.get('StatusCode', 0) != 0:
                raise RuntimeError(result.get('msg') or result.get('StatusMessage') or f'HTTP {response.status_code}')
            event['status'] = 'sent'
        except Exception as exc:
            event.update({'status': 'failed', 'error': str(exc)})
        session.alerts = alerts
        session.save(update_fields=['alerts', 'updated_at'])

    def _finish_session(self, session_id, reason):
        session = DouyinMonitorSession.objects.filter(id=session_id, ended_at__isnull=True).first()
        if not session:
            return
        now = timezone.now()
        points = list(session.points or [])
        if session.current_count is not None:
            now_ms = timestamp_ms(now)
            if not points or now_ms - int(points[-1]['time']) >= 1000:
                points.append({'time': now_ms, 'count': session.current_count})
        session.status = DouyinMonitorSession.Status.STOPPED
        session.status_message = reason
        session.ended_at = now
        session.end_reason = reason
        session.points = points
        session.stream_url = ''
        session.save(update_fields=[
            'status', 'status_message', 'ended_at', 'end_reason', 'points', 'stream_url', 'updated_at',
        ])


monitor_manager = DouyinMonitorManager()
