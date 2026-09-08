"""Tests for the JustWatch deep link lookup."""

from types import SimpleNamespace
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase

from app.models import MediaTypes
from app.providers import justwatch


def _search_result(tmdb_id, entry_id="ts1"):
    """Build a minimal stand-in for a JustWatch search result."""
    return SimpleNamespace(tmdb_id=tmdb_id, entry_id=entry_id)


def _offer(package_id, url, monetization_type="FLATRATE"):
    """Build a minimal stand-in for a JustWatch offer."""
    return SimpleNamespace(
        monetization_type=monetization_type,
        url=url,
        package=SimpleNamespace(package_id=package_id),
    )


class GetDeeplinksTest(TestCase):
    """Test justwatch.get_deeplinks()."""

    def setUp(self):
        """Clear any cached lookups so tests don't leak into each other."""
        cache.clear()

    @patch("app.providers.justwatch.offers_for_countries")
    @patch("app.providers.justwatch.search")
    def test_matches_by_tmdb_id_and_filters_to_flatrate_and_free(
        self,
        mock_search,
        mock_offers,
    ):
        """A matching title returns flatrate/free deep links, keyed by provider id."""
        mock_search.return_value = [
            _search_result(tmdb_id="9999", entry_id="wrong"),
            _search_result(tmdb_id="1396", entry_id="ts4"),
        ]
        mock_offers.return_value = {
            "US": [
                _offer(8, "https://www.netflix.com/title/70143836", "FLATRATE"),
                _offer(9, "https://www.hulu.com/watch/free-title", "FREE"),
                _offer(9, "https://www.hulu.com/watch/rent-title", "RENT"),
                _offer(2, "https://tv.apple.com/buy-title", "BUY"),
            ],
        }

        deeplinks = justwatch.get_deeplinks(
            MediaTypes.TV.value,
            "1396",
            "Breaking Bad",
            "US",
        )

        self.assertEqual(
            deeplinks,
            {
                8: "https://www.netflix.com/title/70143836",
                9: "https://www.hulu.com/watch/free-title",
            },
        )
        mock_search.assert_called_once_with(
            "Breaking Bad",
            "US",
            "en",
            5,
            object_types=["SHOW"],
        )
        mock_offers.assert_called_once_with("ts4", {"US"})

    @patch("app.providers.justwatch.offers_for_countries")
    @patch("app.providers.justwatch.search")
    def test_no_matching_tmdb_id_returns_empty_without_fetching_offers(
        self,
        mock_search,
        mock_offers,
    ):
        """When no search result matches the tmdb_id, no offers call is made."""
        mock_search.return_value = [_search_result(tmdb_id="4242", entry_id="ts4")]

        deeplinks = justwatch.get_deeplinks(
            MediaTypes.TV.value,
            "1396",
            "Breaking Bad",
            "US",
        )

        self.assertEqual(deeplinks, {})
        mock_offers.assert_not_called()

    @patch("app.providers.justwatch.offers_for_countries")
    @patch("app.providers.justwatch.search")
    def test_node_id_lookup_is_cached(self, mock_search, mock_offers):
        """A second call for the same title doesn't search JustWatch again."""
        mock_search.return_value = [_search_result(tmdb_id="1396", entry_id="ts4")]
        mock_offers.return_value = {"US": []}

        justwatch.get_deeplinks(MediaTypes.TV.value, "1396", "Breaking Bad", "US")
        justwatch.get_deeplinks(MediaTypes.TV.value, "1396", "Breaking Bad", "US")

        mock_search.assert_called_once()

    @patch("app.providers.justwatch.offers_for_countries")
    @patch("app.providers.justwatch.search")
    def test_no_match_is_also_cached(self, mock_search, mock_offers):
        """An unmatched title isn't re-searched on every request either."""
        mock_search.return_value = []

        justwatch.get_deeplinks(MediaTypes.TV.value, "1396", "Breaking Bad", "US")
        justwatch.get_deeplinks(MediaTypes.TV.value, "1396", "Breaking Bad", "US")

        mock_search.assert_called_once()
        mock_offers.assert_not_called()

    @patch("app.providers.justwatch.offers_for_countries")
    @patch("app.providers.justwatch.search")
    def test_offers_lookup_is_cached(self, mock_search, mock_offers):
        """A second call for the same resolved title doesn't refetch offers."""
        mock_search.return_value = [_search_result(tmdb_id="1396", entry_id="ts4")]
        mock_offers.return_value = {
            "US": [_offer(8, "https://www.netflix.com/title/70143836")],
        }

        justwatch.get_deeplinks(MediaTypes.TV.value, "1396", "Breaking Bad", "US")
        justwatch.get_deeplinks(MediaTypes.TV.value, "1396", "Breaking Bad", "US")

        mock_offers.assert_called_once()

    @patch("app.providers.justwatch.search")
    def test_search_failure_degrades_to_empty(self, mock_search):
        """An upstream error from the unofficial API never propagates."""
        mock_search.side_effect = RuntimeError("JustWatch schema changed")

        deeplinks = justwatch.get_deeplinks(
            MediaTypes.MOVIE.value,
            "27205",
            "Inception",
            "US",
        )

        self.assertEqual(deeplinks, {})

    @patch("app.providers.justwatch.offers_for_countries")
    @patch("app.providers.justwatch.search")
    def test_offers_failure_degrades_to_empty(self, mock_search, mock_offers):
        """A failure fetching offers never propagates either."""
        mock_search.return_value = [_search_result(tmdb_id="27205", entry_id="tm1")]
        mock_offers.side_effect = RuntimeError("JustWatch schema changed")

        deeplinks = justwatch.get_deeplinks(
            MediaTypes.MOVIE.value,
            "27205",
            "Inception",
            "US",
        )

        self.assertEqual(deeplinks, {})

    @patch("app.providers.justwatch.search")
    def test_missing_title_returns_empty_without_calling_justwatch(self, mock_search):
        """No title means nothing to search for."""
        deeplinks = justwatch.get_deeplinks(MediaTypes.MOVIE.value, "27205", "", "US")

        self.assertEqual(deeplinks, {})
        mock_search.assert_not_called()

    @patch("app.providers.justwatch.search")
    def test_missing_region_returns_empty_without_calling_justwatch(self, mock_search):
        """No region means nothing to filter offers by."""
        deeplinks = justwatch.get_deeplinks(
            MediaTypes.MOVIE.value,
            "27205",
            "Inception",
            "",
        )

        self.assertEqual(deeplinks, {})
        mock_search.assert_not_called()

    @patch("app.providers.justwatch.search")
    def test_unsupported_media_type_returns_empty_without_calling_justwatch(
        self,
        mock_search,
    ):
        """Only tv/movie are supported; anything else is a no-op."""
        deeplinks = justwatch.get_deeplinks("anime", "1", "Some Anime", "US")

        self.assertEqual(deeplinks, {})
        mock_search.assert_not_called()
