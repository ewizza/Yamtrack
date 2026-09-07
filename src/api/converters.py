"""URL converters for the API app."""


class TvMovieType:
    """Restrict a URL segment to the "tv" or "movie" media types."""

    regex = "(tv|movie)"

    def to_python(self, value):
        """Return the matched media type as-is."""
        return value

    def to_url(self, value):
        """Return the media type as-is for URL reversal."""
        return value
