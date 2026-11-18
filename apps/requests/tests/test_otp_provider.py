import io
import json
import urllib.error
from unittest import mock

from django.test import TestCase

from apps.core.models import SystemParameter
from apps.requests.models import OtpVerification, RequestMessageLog
from apps.requests.services import otp


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _params(**values):
    for key, value in values.items():
        SystemParameter.objects.update_or_create(key=key, defaults={'value': value})


class MelliPayamakOtpTests(TestCase):
    def setUp(self):
        _params(sms_enabled='true', sms_provider='melipayamak', sms_otp_key='testkey123',
                sms_username='u', sms_api_key='p')

    def test_code_from_melipayamak_is_stored(self):
        reply = _Resp(json.dumps({'code': '3741437414', 'status': ''}).encode())
        with mock.patch('urllib.request.urlopen', return_value=reply) as call:
            record = otp.issue(mobile='09120000001', purpose='login')
        self.assertEqual(record.code, '3741437414')
        sent = call.call_args[0][0]
        self.assertTrue(sent.full_url.endswith('/api/send/otp/testkey123'))
        self.assertEqual(json.loads(sent.data), {'to': '09120000001'})
        log = RequestMessageLog.objects.get(mobile='09120000001')
        self.assertEqual(log.status, RequestMessageLog.Status.SENT)
        self.assertEqual(log.provider, 'melipayamak-otp')
        # The user types the code MelliPayamak sent and it verifies.
        otp.verify(mobile='09120000001', code='3741437414', purpose='login')

    def test_falls_back_to_own_code_when_service_fails(self):
        def fail_then_pattern(req, timeout=None):
            if 'console.melipayamak.com' in req.full_url:
                raise urllib.error.URLError('down')
            return _Resp(json.dumps({'Value': '5221022493414465419', 'RetStatus': 1}).encode())
        with mock.patch('urllib.request.urlopen', side_effect=fail_then_pattern):
            record = otp.issue(mobile='09120000002', purpose='login')
        self.assertEqual(len(record.code), otp.OTP_LENGTH)
        self.assertEqual(OtpVerification.objects.filter(mobile='09120000002').count(), 1)

    def test_contract_code_uses_contract_pattern_with_name(self):
        from apps.requests.services import lifecycle
        req = lifecycle.create_request(full_name='زهرا سلمانی', mobile='09120000004', province='تهران')
        reply = _Resp(b'{"Value":"5221022493414465419","RetStatus":1}')
        with mock.patch('urllib.request.urlopen', return_value=reply) as call:
            record = otp.issue(mobile='09120000004', purpose='contract_approval', request=req)
        sent = call.call_args[0][0]
        self.assertTrue(sent.full_url.endswith('/BaseServiceNumber'))
        body = json.loads(sent.data)
        self.assertEqual(body['bodyId'], '520895')
        self.assertEqual(body['text'], f'زهرا سلمانی;{record.code}')

    def test_lead_link_uses_lead_pattern(self):
        from apps.requests.services import sms
        reply = _Resp(b'{"Value":"5221022493414465419","RetStatus":1}')
        with mock.patch('urllib.request.urlopen', return_value=reply) as call:
            log = sms.send_message(mobile='09120000005', body='plain text',
                                   message_type=RequestMessageLog.MessageType.LEAD,
                                   pattern=(sms.LEAD_LINK_PATTERN, ['زهرا', 'Agy5Kly']))
        raw = call.call_args[0][0].data
        self.assertIn('زهرا'.encode('utf-8'), raw)  # sent as UTF-8, not \u-escaped
        body = json.loads(raw)
        self.assertEqual(body['bodyId'], '564762')
        self.assertEqual(body['text'], 'زهرا;Agy5Kly')
        self.assertEqual(log.status, RequestMessageLog.Status.SENT)

    def test_status_change_uses_status_pattern(self):
        from apps.requests.services import lifecycle
        req = lifecycle.create_request(full_name='ت', mobile='09120000006', province='تهران')
        reply = _Resp(b'{"Value":"5221022493414465419","RetStatus":1}')
        with mock.patch('urllib.request.urlopen', return_value=reply) as call:
            lifecycle.transition(req, 'hold')
        body = json.loads(call.call_args[0][0].data)
        self.assertEqual(body['bodyId'], '565044')
        self.assertEqual(body['text'], f'{req.id};{req.get_status_display()}')

    def test_not_used_without_key(self):
        SystemParameter.objects.filter(key='sms_otp_key').delete()
        with mock.patch('urllib.request.urlopen',
                        return_value=_Resp(b'{"Value":"5221022493414465419","RetStatus":1}')) as call:
            record = otp.issue(mobile='09120000003', purpose='login')
        self.assertEqual(len(record.code), otp.OTP_LENGTH)
        self.assertNotIn('console.melipayamak.com', call.call_args[0][0].full_url)
