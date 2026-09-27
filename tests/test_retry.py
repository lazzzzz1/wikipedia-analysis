import requests

from wikitrends import wikimedia_api as api


def _http_error(status, headers=None):
    resp = requests.Response()
    resp.status_code = status
    resp.headers.update(headers or {})
    return requests.HTTPError(response=resp)


def test_retry_honors_retry_after_on_429_but_caps_it():
    assert api._retry_delay(_http_error(429, {"Retry-After": "12"}), 0) == 12
    assert api._retry_delay(_http_error(429, {"Retry-After": "600"}), 0) == 30


def test_retry_backoff_grows_exponentially():
    assert api._retry_delay(_http_error(503), 0) == 1.5
    assert api._retry_delay(_http_error(503), 2) == 6.0
