import unittest
import urllib.error
from unittest.mock import MagicMock, patch

from tle import (
    MISSING_TTL_SECONDS, USER_AGENT, NoElements, Tle, TleCache, download, fetch_from_celestrak,
    parse_tle_response,
)

# What CelesTrak actually answered for NOAA 19 on 2026-09-22: CRLF line endings
# and the name padded with spaces to 24 characters.
CELESTRAK_RESPONSE = (
    'NOAA 19                 \r\n'
    '1 33591U 09005A   26265.59422357 -.00000002  00000+0  22595-4 0  9992\r\n'
    '2 33591  98.9435 336.4970 0014750 113.5139 246.7585 14.13486520908247\r\n'
)


class ParseTleResponseTests(unittest.TestCase):
    def test_reads_what_celestrak_returns(self):
        tle = parse_tle_response(CELESTRAK_RESPONSE)

        self.assertEqual(tle.name, 'NOAA 19')
        self.assertTrue(tle.line1.startswith('1 33591U'))
        self.assertTrue(tle.line2.startswith('2 33591'))

    def test_unknown_catalog_number_is_an_error(self):
        # CelesTrak answers 200 with this text, so it has to be caught by content.
        with self.assertRaises(NoElements):
            parse_tle_response('No GP data found')

    def test_anything_that_is_not_three_lines_is_an_error(self):
        for text in ('', 'garbage', 'NOAA 19\n1 33591U 09005A', CELESTRAK_RESPONSE + 'extra\n'):
            with self.subTest(text=text[:20]):
                with self.assertRaises(ValueError):
                    parse_tle_response(text)

    def test_element_lines_must_be_numbered(self):
        text = 'NOAA 19\nfirst line\nsecond line\n'

        with self.assertRaises(ValueError):
            parse_tle_response(text)


class DownloadTests(unittest.TestCase):
    def test_identifies_itself_to_celestrak(self):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = CELESTRAK_RESPONSE.encode()

        with patch('tle.urllib.request.urlopen', return_value=response) as urlopen:
            text = download('https://example.org/tle', timeout=5)

        request = urlopen.call_args.args[0]
        self.assertEqual(request.get_header('User-agent'), USER_AGENT)
        self.assertEqual(urlopen.call_args.kwargs, {'timeout': 5})
        self.assertEqual(text, CELESTRAK_RESPONSE)


def http_error(code):
    return urllib.error.HTTPError('https://celestrak.org', code, 'error', {}, None)


class FetchFromCelestrakTests(unittest.TestCase):
    def test_a_404_means_there_are_no_elements(self):
        # What CelesTrak answered for 99433, 88259 and the like in November 2026.
        with patch('tle.download', side_effect=http_error(404)):
            with self.assertRaises(NoElements):
                fetch_from_celestrak(99433)

    def test_other_failures_are_not_mistaken_for_a_missing_satellite(self):
        for error in (http_error(500), http_error(403), urllib.error.URLError('timed out')):
            with self.subTest(error=error):
                with patch('tle.download', side_effect=error):
                    with self.assertRaises(urllib.error.URLError) as raised:
                        fetch_from_celestrak(33591)
                self.assertNotIsInstance(raised.exception, NoElements)


class FakeClock:
    def __init__(self, now=0.0):
        self.now = now

    def __call__(self):
        return self.now


class TleCacheTests(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.tle = Tle('NOAA 19', '1 33591U', '2 33591')
        self.fetch = MagicMock(return_value=self.tle)
        self.cache = TleCache(ttl_seconds=3600, fetch=self.fetch, clock=self.clock)

    def test_first_access_downloads(self):
        self.assertEqual(self.cache.get(33591), self.tle)
        self.fetch.assert_called_once_with(33591)

    def test_within_the_ttl_nothing_is_downloaded_again(self):
        self.cache.get(33591)
        self.clock.now = 3599

        self.cache.get(33591)

        self.fetch.assert_called_once()

    def test_past_the_ttl_it_downloads_again(self):
        self.cache.get(33591)
        self.clock.now = 3600

        self.cache.get(33591)

        self.assertEqual(self.fetch.call_count, 2)

    def test_each_satellite_has_its_own_entry(self):
        self.cache.get(33591)
        self.cache.get(25544)

        self.assertEqual(self.fetch.call_count, 2)

    def test_a_failed_refresh_falls_back_to_the_stale_elements(self):
        self.cache.get(33591)
        self.clock.now = 7200
        self.fetch.side_effect = OSError('celestrak unreachable')

        with self.assertLogs('tle', level='WARNING'):
            self.assertEqual(self.cache.get(33591), self.tle)

    def test_a_failure_with_nothing_cached_propagates(self):
        self.fetch.side_effect = OSError('celestrak unreachable')

        with self.assertRaises(OSError):
            self.cache.get(33591)

    def test_a_failed_refresh_does_not_poison_the_next_one(self):
        self.cache.get(33591)
        self.clock.now = 7200
        self.fetch.side_effect = OSError('celestrak unreachable')
        with self.assertLogs('tle', level='WARNING'):
            self.cache.get(33591)

        self.fetch.side_effect = None
        self.cache.get(33591)

        # The stale entry was not refreshed by the failure, so it tries again.
        self.assertEqual(self.fetch.call_count, 3)



class MissingSatelliteTests(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.tle = Tle('NOAA 19', '1 33591U', '2 33591')
        self.fetch = MagicMock(side_effect=NoElements('no elements'))
        self.cache = TleCache(ttl_seconds=3600, fetch=self.fetch, clock=self.clock)

    def miss(self, norad=99433):
        with self.assertRaises(NoElements):
            self.cache.get(norad)

    def test_the_default_is_a_day(self):
        self.assertEqual(MISSING_TTL_SECONDS, 24 * 3600)
        self.assertEqual(self.cache.missing_ttl_seconds, 24 * 3600)

    def test_a_missing_satellite_is_asked_for_once_a_day_at_most(self):
        with self.assertLogs('tle', level='WARNING'):
            self.miss()
        for minutes in (1, 60, 23 * 60):
            self.clock.now = minutes * 60
            self.miss()

        self.fetch.assert_called_once_with(99433)

    def test_it_warns_once_per_ban(self):
        with self.assertLogs('tle', level='WARNING') as logs:
            self.miss()
        self.assertEqual(len(logs.records), 1)

        self.clock.now = 60
        with self.assertNoLogs('tle', level='WARNING'):
            self.miss()

    def test_after_a_day_it_asks_again(self):
        with self.assertLogs('tle', level='WARNING'):
            self.miss()
        self.clock.now = MISSING_TTL_SECONDS

        with self.assertLogs('tle', level='WARNING'):
            self.miss()

        self.assertEqual(self.fetch.call_count, 2)

    def test_a_satellite_that_shows_up_is_no_longer_banned(self):
        with self.assertLogs('tle', level='WARNING'):
            self.miss()
        self.clock.now = MISSING_TTL_SECONDS
        self.fetch.side_effect = None
        self.fetch.return_value = self.tle

        self.assertEqual(self.cache.get(99433), self.tle)
        # Expire the TLE itself and lose CelesTrak for good: the next miss bans again.
        self.clock.now += 3600
        self.fetch.side_effect = NoElements('gone')
        with self.assertLogs('tle', level='WARNING'):
            self.assertEqual(self.cache.get(99433), self.tle)
        self.assertEqual(self.fetch.call_count, 3)

    def test_one_banned_satellite_does_not_affect_the_others(self):
        with self.assertLogs('tle', level='WARNING'):
            self.miss(99433)
        self.fetch.side_effect = None
        self.fetch.return_value = self.tle

        self.assertEqual(self.cache.get(33591), self.tle)

    def test_stale_elements_are_kept_and_not_asked_for_again(self):
        self.fetch.side_effect = None
        self.fetch.return_value = self.tle
        self.cache.get(33591)
        self.clock.now = 7200
        self.fetch.side_effect = NoElements('decayed')

        with self.assertLogs('tle', level='WARNING'):
            self.assertEqual(self.cache.get(33591), self.tle)
        self.clock.now = 7260
        self.assertEqual(self.cache.get(33591), self.tle)

        self.assertEqual(self.fetch.call_count, 2)


if __name__ == '__main__':
    unittest.main()
