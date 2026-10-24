import unittest
from io import BytesIO
from urllib.error import HTTPError
from email.utils import formatdate
from unittest.mock import patch

from paper_collector.arxiv import build_query, fetch_recent


FEED = b'''<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry><id>http://arxiv.org/abs/2601.00001v1</id><title>LLM inference</title>
  <updated>2026-01-01T00:00:00Z</updated><published>2026-01-01T00:00:00Z</published>
  <summary>KV cache serving.</summary><author><name>Ada</name></author>
  <link href="https://arxiv.org/pdf/2601.00001v1" title="pdf"/><category term="cs.CL"/></entry>
</feed>'''


class Response(BytesIO):
    def __enter__(self): return self
    def __exit__(self, *_): self.close()


class ArxivTests(unittest.TestCase):
    def test_query_combines_categories(self):
        self.assertEqual(build_query(["cs.CL", "cs.AI"]), "cat:cs.CL OR cat:cs.AI")

    @patch("paper_collector.arxiv.time.sleep")
    @patch("paper_collector.arxiv.urlopen")
    def test_rate_limit_is_retried(self, mocked_open, mocked_sleep):
        mocked_open.side_effect = [HTTPError("url", 429, "limited", {}, None), Response(FEED)]
        papers = fetch_recent(["cs.CL"], 1, "test-agent", retries=2)
        self.assertEqual(papers[0].paper_id, "2601.00001v1")
        mocked_sleep.assert_called_once_with(15)

    @patch("paper_collector.arxiv.time.sleep")
    @patch("paper_collector.arxiv.urlopen")
    def test_repeated_rate_limits_exhaust_bounded_retries(self, mocked_open, mocked_sleep):
        mocked_open.side_effect = HTTPError("url", 429, "limited", {}, None)
        with self.assertRaises(HTTPError):
            fetch_recent(["cs.CL"], 1, "test-agent")
        self.assertEqual(mocked_open.call_count, 5)
        self.assertEqual([call.args[0] for call in mocked_sleep.call_args_list], [15, 30, 60, 120])

    @patch("paper_collector.arxiv.time.sleep")
    @patch("paper_collector.arxiv.urlopen")
    def test_retry_after_seconds_and_http_date_are_respected(self, mocked_open, mocked_sleep):
        for retry_after in ["90", formatdate(1_800_000_090, usegmt=True)]:
            with self.subTest(retry_after=retry_after):
                mocked_open.side_effect = [HTTPError("url", 503, "busy", {"Retry-After": retry_after}, None), Response(FEED)]
                mocked_sleep.reset_mock()
                with patch("paper_collector.arxiv.time.time", return_value=1_800_000_000):
                    self.assertEqual(len(fetch_recent(["cs.CL"], 1, "test-agent")), 1)
                mocked_sleep.assert_called_once_with(90)

    @patch("paper_collector.arxiv.time.sleep")
    @patch("paper_collector.arxiv.urlopen")
    def test_retry_after_outside_budget_fails_without_retrying_early(self, mocked_open, mocked_sleep):
        mocked_open.side_effect = HTTPError("url", 429, "limited", {"Retry-After": "2000"}, None)
        with self.assertRaises(HTTPError):
            fetch_recent(["cs.CL"], 1, "test-agent")
        self.assertEqual(mocked_open.call_count, 1)
        mocked_sleep.assert_not_called()

    @patch("paper_collector.arxiv.time.sleep")
    @patch("paper_collector.arxiv.urlopen")
    def test_socket_timeout_is_retried(self, mocked_open, mocked_sleep):
        mocked_open.side_effect = [TimeoutError("read timed out"), Response(FEED)]
        self.assertEqual(len(fetch_recent(["cs.CL"], 1, "test-agent")), 1)
        mocked_sleep.assert_called_once_with(15)

    @patch("paper_collector.arxiv.time.sleep")
    @patch("paper_collector.arxiv.urlopen")
    def test_permanent_http_error_is_not_retried(self, mocked_open, mocked_sleep):
        mocked_open.side_effect = HTTPError("url", 403, "forbidden", {}, None)
        with self.assertRaises(HTTPError):
            fetch_recent(["cs.CL"], 1, "test-agent")
        self.assertEqual(mocked_open.call_count, 1)
        mocked_sleep.assert_not_called()

    @patch("paper_collector.arxiv.urlopen")
    def test_arxiv_error_feed_is_not_saved_as_empty_success(self, mocked_open):
        mocked_open.return_value = Response(b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>http://arxiv.org/api/errors#query</id><title>Error</title></entry></feed>')
        with self.assertRaises(ValueError):
            fetch_recent(["cs.CL"], 1, "test-agent")

    @patch("paper_collector.arxiv.urlopen")
    def test_legitimate_empty_feed_is_accepted(self, mocked_open):
        mocked_open.return_value = Response(b'<feed xmlns="http://www.w3.org/2005/Atom"/>')
        self.assertEqual(fetch_recent(["cs.CL"], 1, "test-agent"), [])
