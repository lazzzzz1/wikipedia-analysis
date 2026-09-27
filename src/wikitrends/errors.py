"""User-facing error types. The CLI catches these and reports them as JSON
instead of a raw traceback, so an agent (especially a small model) always
gets a parseable {"error": ...} object."""


class WikitrendsError(Exception):
    """Base class for expected, user-facing errors."""


class ArticleNotFoundError(WikitrendsError):
    pass


class TopicNotFoundError(WikitrendsError):
    pass
