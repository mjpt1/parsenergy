import io
import json
import urllib.error
from unittest import mock

from django.test import TestCase

from apps.core import geocoding
from apps.core.models import SystemParameter

NESHAN_REPLY = {'status': 'OK', 'formatted_address': 'تهران، خیابان آزادی',
                'city': 'تهران', 'state': 'استان تهران'}


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _fake_open(mapir_ok: bool):
    def opener_open(req, timeout=None):
        url = req.full_url
        if 'map.ir' in url:
            if not mapir_ok:
                raise urllib.error.URLError('down')
            return _Resp(json.dumps({'address': 'map.ir address', 'province': 'تهران',
                                     'city': 'تهران'}).encode())
        if 'neshan' in url:
            return _Resp(json.dumps(NESHAN_REPLY).encode())
        raise AssertionError(url)
    return opener_open


class GeocodingFallbackTests(TestCase):
    def setUp(self):
        SystemParameter.objects.create(key='map_api_key', value='m')
        SystemParameter.objects.create(key='neshan_api_key', value='n')

    def _reverse(self, mapir_ok):
        opener = mock.Mock()
        opener.open.side_effect = _fake_open(mapir_ok)
        with mock.patch('urllib.request.build_opener', return_value=opener):
            return geocoding.reverse(35.7, 51.4)

    def test_mapir_used_first(self):
        self.assertEqual(self._reverse(True)['address'], 'map.ir address')

    def test_neshan_used_when_mapir_fails(self):
        result = self._reverse(False)
        self.assertEqual(result['address'], 'تهران، خیابان آزادی')
        self.assertEqual(result['province'], 'تهران')

    def test_error_when_mapir_fails_and_no_neshan_key(self):
        SystemParameter.objects.filter(key='neshan_api_key').delete()
        with self.assertRaises(geocoding.GeocodingError):
            self._reverse(False)
