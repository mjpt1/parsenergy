import io

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from PIL import Image


def photo(name):
    b = io.BytesIO()
    Image.new('RGB', (40, 30), 'green').save(b, 'JPEG')
    return SimpleUploadedFile(name, b.getvalue(), content_type='image/jpeg')


DATA = dict(
    customer='کارخانه مامک <b>شمال</b>', location='استان مازندران', doc_no='PET-26-09-MM-PQ-01', date='1405/07/01',
    site_desc='سقف کارخانه', site_type='سقف', site_note='سقف سوله', kwp='124', mwh='172.9', modules='200', wp='620',
    inv_n='1', inv_kw='125', pr='86.1', tool='PVsyst', monthly='۱۱٫۲، 13.1, 15.8, 17.2, 17, 16.4, 15.1, 13.6, 12, 11.4, 11.9, 13.2',
    rate='72000', rate_src='بورس انرژی', rate_date='1405/07/04', capex='250000000000', phase1_fee='170000000',
)


class ProposalTests(TestCase):
    def test_admin_gets_filled_five_pages(self):
        get_user_model().objects.create_superuser(username='mjpt1', password='Zx9!kQ2mVr7t', role='admin')
        self.client.login(username='mjpt1', password='Zx9!kQ2mVr7t')
        r = self.client.post('/reports/proposal/', {**DATA, 'layout': photo('a.jpg'), 'site': photo('b.jpg')})
        html = r.content.decode()
        self.assertEqual(r.status_code, 200)
        self.assertEqual(html.count('class="page'), 5)
        self.assertIn('&lt;b&gt;شمال', html)            # user text is escaped
        self.assertIn('۱۲٬۴۴۸٬۸۰۰٬۰۰۰', html)          # 172,900 kWh x 72,000 rial
        self.assertIn('img/proposal-cover', html)  # fixed cover photo

    def test_bad_monthly_shows_form_error(self):
        get_user_model().objects.create_superuser(username='mjpt1', password='Zx9!kQ2mVr7t', role='admin')
        self.client.login(username='mjpt1', password='Zx9!kQ2mVr7t')
        r = self.client.post('/reports/proposal/', {**DATA, 'monthly': '1,2,3', 'layout': photo('a.jpg'), 'site': photo('b.jpg')})
        self.assertContains(r, 'تولید هر ۱۲ ماه را وارد کنید')

    def test_everyone_but_the_trial_account_is_refused(self):
        self._admin('otheradmin')
        self.assertEqual(self.client.get('/reports/proposal/').status_code, 403)
        self.assertNotContains(self.client.get('/reports/'), '/reports/proposal/')

    def _admin(self, name):
        get_user_model().objects.create_superuser(username=name, password='Zx9!kQ2mVr7t', role='admin')
        self.client.login(username=name, password='Zx9!kQ2mVr7t')

    def _post(self, **over):
        data = {**DATA, 'layout': photo('a.jpg'), 'site': photo('b.jpg'), **over}
        return self.client.post('/reports/proposal/', data, HTTP_X_REQUESTED_WITH='XMLHttpRequest')

    def test_ajax_errors_come_back_as_json(self):
        self._admin('mjpt1')
        r = self._post(monthly=','.join(['0'] * 12), kwp='abc')   # a year of zeros used to crash the chart
        self.assertEqual(r.status_code, 400)
        self.assertEqual(set(r.json()['errors']), {'monthly', 'kwp'})

    def test_ajax_success_is_the_bare_proposal(self):
        self._admin('mjpt1')
        r = self._post(capex='۲۵۰٬۰۰۰٬۰۰۰٬۰۰۰', mwh='۱۷۲٫۹', pr='86.10')   # Persian digits and separators
        html = r.content.decode()
        self.assertEqual(r.status_code, 200)
        self.assertNotIn('class="toolbar"', html)
        self.assertIn('۲۵۰٬۰۰۰٬۰۰۰٬۰۰۰', html)
        self.assertIn('۱۲٬۴۴۸٬۸۰۰٬۰۰۰', html)

    def test_phone_photo_rotation_is_applied(self):
        import base64
        from apps.reports.proposal import image_uri
        b = io.BytesIO()
        exif = Image.Exif()
        exif[0x0112] = 6   # "rotate 90" as phones store portrait shots
        Image.new('RGB', (40, 20)).save(b, 'JPEG', exif=exif)
        out = Image.open(io.BytesIO(base64.b64decode(image_uri(io.BytesIO(b.getvalue())).split(',')[1])))
        self.assertEqual(out.size, (20, 40))
