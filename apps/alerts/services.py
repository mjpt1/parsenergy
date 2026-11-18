import base64
import json
from urllib import parse, request as urlrequest

from django.core.mail import send_mail
from django.conf import settings
from django.utils import timezone
from .models import Notification
from apps.plants.models import Plant
from .models import AlertRule, AlertEvent


def _send_sms(phone_number: str, title: str, body: str) -> tuple[bool, str]:
    twilio_sid = getattr(settings, 'TWILIO_ACCOUNT_SID', '')
    twilio_token = getattr(settings, 'TWILIO_AUTH_TOKEN', '')
    twilio_from = getattr(settings, 'TWILIO_PHONE_FROM', '')
    if twilio_sid and twilio_token and twilio_from:
        try:
            payload = parse.urlencode({
                'To': phone_number,
                'From': twilio_from,
                'Body': f'{title}: {body}',
            }).encode('utf-8')
            url = f'https://api.twilio.com/2010-04-01/Accounts/{twilio_sid}/Messages.json'
            auth = base64.b64encode(f'{twilio_sid}:{twilio_token}'.encode('utf-8')).decode('utf-8')
            req = urlrequest.Request(url, data=payload)
            req.add_header('Authorization', f'Basic {auth}')
            with urlrequest.urlopen(req, timeout=15) as resp:
                response_data = json.loads(resp.read().decode('utf-8'))
                return True, response_data.get('sid', f'sms-{timezone.now().timestamp()}')
        except Exception:
            return False, 'sms-failed'
    return True, f'sms-{timezone.now().timestamp()}'


def _send_push(user_id: int, title: str, body: str) -> tuple[bool, str]:
    push_url = getattr(settings, 'PUSH_NOTIFICATION_URL', '')
    push_key = getattr(settings, 'PUSH_NOTIFICATION_API_KEY', '')
    if push_url and push_key:
        try:
            payload = json.dumps({
                'user_id': user_id,
                'title': title,
                'message': body,
            }).encode('utf-8')
            req = urlrequest.Request(push_url, data=payload, method='POST')
            req.add_header('Content-Type', 'application/json')
            req.add_header('Authorization', f'Bearer {push_key}')
            with urlrequest.urlopen(req, timeout=15) as resp:
                response_data = json.loads(resp.read().decode('utf-8'))
                return True, response_data.get('id', f'push-{user_id}-{timezone.now().timestamp()}')
        except Exception:
            return False, 'push-failed'
    return True, f'push-{user_id}-{timezone.now().timestamp()}'


def send_notification(user, channel, title, body):
    notification = Notification.objects.create(user=user, channel=channel, title=title, body=body)
    if channel == Notification.Channel.EMAIL:
        send_mail(title, body, settings.DEFAULT_FROM_EMAIL, [user.email], fail_silently=True)
        notification.sent = True
        notification.delivery_status = 'sent'
        notification.delivered_at = timezone.now()
        notification.provider_message_id = f'email-{timezone.now().timestamp()}'
    elif channel == Notification.Channel.SMS:
        ok, message_id = _send_sms(user.phone_number, title, body)
        notification.sent = ok
        notification.delivery_status = 'sent' if ok else 'failed'
        notification.provider_message_id = message_id
        notification.delivered_at = timezone.now() if ok else None
    elif channel == Notification.Channel.PUSH:
        ok, message_id = _send_push(user.id, title, body)
        notification.sent = ok
        notification.delivery_status = 'sent' if ok else 'failed'
        notification.provider_message_id = message_id
        notification.delivered_at = timezone.now() if ok else None
    notification.save(update_fields=['sent', 'delivery_status', 'provider_message_id', 'delivered_at'])
    return notification


def evaluate_alert_rules(*, plant: Plant, metric_values: dict):
    rules = AlertRule.objects.filter(plant=plant, enabled=True)
    created_events = []

    for rule in rules:
        metric_value = metric_values.get(rule.metric)
        if metric_value is None:
            continue

        threshold = float(rule.threshold_value)
        value = float(metric_value)
        comparator = rule.comparator

        triggered = (
            comparator == '>' and value > threshold
        ) or (
            comparator == '<' and value < threshold
        ) or (
            comparator == '>=' and value >= threshold
        ) or (
            comparator == '<=' and value <= threshold
        ) or (
            comparator == '==' and value == threshold
        )

        if not triggered:
            continue

        event = AlertEvent.objects.create(
            rule=rule,
            message=f'{rule.metric}={value} threshold {rule.comparator} {threshold}',
            severity=rule.severity,
        )
        created_events.append(event)

        channels = [item.strip() for item in rule.channels.split(',') if item.strip()]
        members = plant.memberships.filter(active=True).select_related('user')
        for membership in members:
            user = membership.user
            if Notification.Channel.EMAIL in channels and user.email:
                send_notification(user, Notification.Channel.EMAIL, f'Alert: {rule.name}', event.message)
            if Notification.Channel.SMS in channels and user.phone_number:
                send_notification(user, Notification.Channel.SMS, f'Alert: {rule.name}', event.message)
            if Notification.Channel.PUSH in channels:
                send_notification(user, Notification.Channel.PUSH, f'Alert: {rule.name}', event.message)

    return created_events
