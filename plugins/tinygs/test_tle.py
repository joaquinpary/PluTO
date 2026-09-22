import unittest
from unittest.mock import MagicMock, patch

from tle import USER_AGENT, Tle, TleCache, download, parse_tle_response

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
        with self.assertRaises(ValueError):
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


if __name__ == '__main__':
    unittest.main()
