"""Shared configuration constants for wikitrends."""

PAGEVIEWS_API_BASE = "https://wikimedia.org/api/rest_v1/metrics/pageviews"
WIKIPEDIA_API_TEMPLATE = "https://{lang}.wikipedia.org/w/api.php"
WIKIDATA_API = "https://www.wikidata.org/w/api.php"

# The Pageviews API has no data before this date.
EARLIEST_AVAILABLE_DATE = "2015-07-01"

DEFAULT_GRANULARITY = "monthly"
DEFAULT_ACCESS = "all-access"
ACCESS_CHOICES = ["all-access", "desktop", "mobile-web", "mobile-app"]
DEFAULT_AGENT = "user"  # excludes bots/spiders -- human reading interest only
DEFAULT_LAST = "24m"

# Trend confidence thresholds
MIN_POINTS_FOR_TREND = 6
LOW_VOLUME_DAILY_VIEWS = 20  # median daily views below this -> low confidence
FLAT_BAND_PCT_PER_YEAR = 3.0  # |trend| below this is reported as "flat"
ANOMALY_MAD_MULTIPLIER = 4.0
ANOMALY_MIN_REL_DEVIATION = 0.25  # and at least 25% away from the local median

REQUEST_TIMEOUT_SECONDS = 20
MAX_RETRIES = 5
RETRY_BACKOFF_SECONDS = 1.5  # doubles each attempt
MAX_RETRY_DELAY_SECONDS = 30

USER_AGENT_ENV_VAR = "WIKITRENDS_CONTACT"
DEFAULT_CONTACT = "no-contact-set (set WIKITRENDS_CONTACT env var)"
