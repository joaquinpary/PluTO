"""The account endpoints: healthcheck, first-run setup and password change."""
import json
import threading
import time
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import OperationalError, connection
from django.test import Client, SimpleTestCase, TestCase, TransactionTestCase

from .test_api import FrontTestCase

STRONG_PASSWORD = 'correct-horse-battery-staple'


class HealthTests(SimpleTestCase):
    def test_answers_ok_when_the_database_answers(self):
        with patch('server_core.api.account.connection'):
            response = self.client.get('/api/health')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'status': 'ok', 'service': 'pluto-backend', 'database': 'ok'})

    def test_answers_503_when_the_database_is_unreachable(self):
        with patch('server_core.api.account.connection') as connection:
            connection.cursor.side_effect = OperationalError('password authentication failed')
            response = self.client.get('/api/health')

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()['database'], 'unreachable')

    def test_a_stale_token_does_not_turn_it_into_a_401(self):
        with patch('server_core.api.account.connection'):
            response = self.client.get('/api/health', HTTP_AUTHORIZATION='Bearer expired-or-garbage')

        self.assertEqual(response.status_code, 200)

    def test_the_root_url_is_no_longer_the_healthcheck(self):
        self.assertEqual(self.client.get('/').status_code, 404)


class SetupTests(TestCase):
    def post(self, body):
        return self.client.post('/api/setup', data=json.dumps(body), content_type='application/json')

    def test_needs_setup_until_a_user_exists(self):
        self.assertEqual(self.client.get('/api/setup').json(), {'needs_setup': True})

        get_user_model().objects.create_user('operator', password='x')

        self.assertEqual(self.client.get('/api/setup').json(), {'needs_setup': False})

    def test_creates_the_only_user_and_it_can_log_in(self):
        response = self.post({'username': 'santi', 'password': STRONG_PASSWORD})

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json(), {'username': 'santi'})
        self.assertTrue(get_user_model().objects.get().is_superuser)
        login = self.client.post('/api/auth/token', data={'username': 'santi', 'password': STRONG_PASSWORD},
                                 content_type='application/json')
        self.assertEqual(login.status_code, 200)

    def test_refuses_once_a_user_exists(self):
        get_user_model().objects.create_user('operator', password='x')

        response = self.post({'username': 'intruder', 'password': STRONG_PASSWORD})

        self.assertEqual(response.status_code, 409)
        self.assertIn('detail', response.json())
        self.assertEqual(get_user_model().objects.count(), 1)

    def test_a_weak_password_is_rejected_by_the_validators(self):
        response = self.post({'username': 'santi', 'password': '1234'})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(list(response.json()), ['password'])
        self.assertFalse(get_user_model().objects.exists())

    def test_an_invalid_username_is_rejected(self):
        response = self.post({'username': 'santi lopez', 'password': STRONG_PASSWORD})

        self.assertEqual(response.status_code, 400)
        self.assertIn('username', response.json())
        self.assertFalse(get_user_model().objects.exists())

    def test_a_stale_token_in_the_browser_does_not_get_in_the_way(self):
        response = self.client.get('/api/setup', HTTP_AUTHORIZATION='Bearer expired-or-garbage')

        self.assertEqual(response.status_code, 200)


class PasswordTests(FrontTestCase):
    def change(self, current, new):
        return self.client.post('/api/auth/password', content_type='application/json',
                                data=json.dumps({'current_password': current, 'new_password': new}))

    def operator(self):
        return get_user_model().objects.get(username='operator')

    def refresh(self, token):
        return Client().post('/api/auth/token/refresh', content_type='application/json',
                             data=json.dumps({'refresh': token}))

    def test_changes_the_password(self):
        response = self.change('x', STRONG_PASSWORD)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(self.operator().check_password(STRONG_PASSWORD))
        self.assertFalse(self.operator().check_password('x'))

    def test_ends_every_other_session_and_hands_this_one_a_new_pair(self):
        # A session on a lost phone, say: its refresh token must stop working.
        other = Client().post('/api/auth/token', content_type='application/json',
                              data=json.dumps({'username': 'operator', 'password': 'x'})).json()['refresh']

        tokens = self.change('x', STRONG_PASSWORD).json()

        self.assertEqual(self.refresh(other).status_code, 401)
        self.assertEqual(self.refresh(tokens['refresh']).status_code, 200)
        me = Client(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}").get('/api/boards')
        self.assertEqual(me.status_code, 200)

    def test_a_wrong_current_password_is_rejected(self):
        response = self.change('not-it', STRONG_PASSWORD)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(list(response.json()), ['current_password'])
        self.assertTrue(self.operator().check_password('x'))

    def test_a_weak_new_password_is_rejected(self):
        response = self.change('x', '1234')

        self.assertEqual(response.status_code, 400)
        self.assertEqual(list(response.json()), ['new_password'])
        self.assertTrue(self.operator().check_password('x'))

    def test_needs_a_login(self):
        response = Client().post('/api/auth/password', content_type='application/json',
                                 data=json.dumps({'current_password': 'x', 'new_password': STRONG_PASSWORD}))

        self.assertEqual(response.status_code, 401)


class ConcurrentSetupTests(TransactionTestCase):
    """Two first-run setups at once (two browsers, or a double click) must not
    leave a second superuser the front end has no way to show."""

    def test_only_one_of_two_simultaneous_setups_creates_a_user(self):
        User = get_user_model()
        create = User.objects.create_superuser

        def slow_create(*args, **kwargs):
            time.sleep(0.5)  # widens the window between the check and the insert
            return create(*args, **kwargs)

        codes = []

        def post(username):
            try:
                codes.append(Client().post('/api/setup', content_type='application/json',
                                           data=json.dumps({'username': username, 'password': STRONG_PASSWORD})).status_code)
            finally:
                connection.close()

        with patch.object(User.objects, 'create_superuser', side_effect=slow_create):
            threads = [threading.Thread(target=post, args=(name,)) for name in ('first', 'second')]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

        self.assertEqual(sorted(codes), [201, 409])
        self.assertEqual(User.objects.count(), 1)
