"""Tests for the JSON API views."""

from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from api.models import DefaultProvider
from app.models import TV, Item, MediaTypes, Movie, Sources, Status
from app.providers import services

NETFLIX_PROVIDER = {
    "provider_id": 8,
    "provider_name": "Netflix",
    "logo_path": "/netflix.jpg",
    "display_priority": 0,
}
HULU_PROVIDER = {
    "provider_id": 15,
    "provider_name": "Hulu",
    "logo_path": "/hulu.jpg",
    "display_priority": 1,
}


class WatchlistViewTest(TestCase):
    """Test the GET /api/watchlist endpoint."""

    def setUp(self):
        """Set up a user with a mix of tracked items."""
        self.credentials = {"username": "test", "password": "testpass"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        self.other_credentials = {"username": "other", "password": "testpass"}
        self.other_user = get_user_model().objects.create_user(
            **self.other_credentials,
        )
        self.url = reverse("api_watchlist")

        tv_item = Item.objects.create(
            media_id="1668",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            title="Test TV Show",
            image="http://example.com/tv.jpg",
        )
        TV.objects.create(
            item=tv_item,
            user=self.user,
            status=Status.IN_PROGRESS.value,
        )

        movie_item = Item.objects.create(
            media_id="238",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="Test Movie",
            image="http://example.com/movie.jpg",
        )
        Movie.objects.create(
            item=movie_item,
            user=self.user,
            status=Status.PLANNING.value,
        )

        # Completed items shouldn't show up in the watchlist.
        completed_item = Item.objects.create(
            media_id="99",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="Completed Movie",
            image="http://example.com/completed.jpg",
        )
        Movie.objects.create(
            item=completed_item,
            user=self.user,
            status=Status.COMPLETED.value,
        )

        # Non-TMDB items have no provider data, so they're excluded too.
        manual_item = Item.objects.create(
            media_id="1",
            source=Sources.MANUAL.value,
            media_type=MediaTypes.MOVIE.value,
            title="Manual Movie",
            image="http://example.com/manual.jpg",
        )
        Movie.objects.create(
            item=manual_item,
            user=self.user,
            status=Status.IN_PROGRESS.value,
        )

        # Another user's items should never leak into this user's watchlist.
        other_item = Item.objects.create(
            media_id="1000",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="Other User Movie",
            image="http://example.com/other.jpg",
        )
        Movie.objects.create(
            item=other_item,
            user=self.other_user,
            status=Status.PLANNING.value,
        )

    def test_valid_token_returns_watchlist(self):
        """A valid token returns the in-progress/planning TMDB tv+movie items."""
        response = self.client.get(
            self.url,
            headers={"Authorization": f"Token {self.user.token}"},
        )

        self.assertEqual(response.status_code, 200)
        results = response.json()["results"]
        titles = {result["title"] for result in results}
        self.assertEqual(titles, {"Test TV Show", "Test Movie"})

    def test_result_shape(self):
        """Each result carries the fields the TV app needs."""
        response = self.client.get(
            self.url,
            headers={"Authorization": f"Token {self.user.token}"},
        )

        results = response.json()["results"]
        tv_result = next(r for r in results if r["title"] == "Test TV Show")
        self.assertEqual(
            tv_result,
            {
                "media_type": "tv",
                "media_id": "1668",
                "title": "Test TV Show",
                "image": "http://example.com/tv.jpg",
                "status": Status.IN_PROGRESS.value,
            },
        )

    def test_missing_token_is_unauthorized(self):
        """A request with no Authorization header is rejected."""
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 401)

    def test_invalid_token_is_unauthorized(self):
        """A request with an unrecognized token is rejected."""
        response = self.client.get(
            self.url,
            headers={"Authorization": "Token not-a-real-token"},
        )

        self.assertEqual(response.status_code, 401)

    def test_only_returns_requesting_users_items(self):
        """Another user's tracked items are never included."""
        response = self.client.get(
            self.url,
            headers={"Authorization": f"Token {self.user.token}"},
        )

        titles = {result["title"] for result in response.json()["results"]}
        self.assertNotIn("Other User Movie", titles)


class ProvidersViewTest(TestCase):
    """Test the GET /api/media/<media_type>/<tmdb_id>/providers endpoint."""

    def setUp(self):
        """Set up an authenticated user."""
        self.credentials = {"username": "test", "password": "testpass"}
        self.user = get_user_model().objects.create_user(**self.credentials)

    def _url(self, media_type="movie", tmdb_id="238"):
        """Build the providers URL for a given media type and tmdb id."""
        return reverse(
            "api_providers",
            kwargs={"media_type": media_type, "tmdb_id": tmdb_id},
        )

    @patch("api.views.services.get_media_metadata")
    def test_returns_providers_for_configured_region(self, mock_get_media_metadata):
        """A configured region returns the filtered, region-specific providers."""
        self.user.watch_provider_region = "US"
        self.user.save()
        mock_get_media_metadata.return_value = {
            "providers": {
                "US": {
                    "flatrate": [
                        {
                            "provider_id": 8,
                            "provider_name": "Netflix",
                            "logo_path": "/netflix.jpg",
                            "display_priority": 0,
                        },
                    ],
                },
            },
        }

        response = self.client.get(
            self._url(),
            headers={"Authorization": f"Token {self.user.token}"},
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["region_configured"])
        self.assertEqual(
            data["providers"],
            [
                {
                    "id": 8,
                    "name": "Netflix",
                    "logo": "https://image.tmdb.org/t/p/w500/netflix.jpg",
                },
            ],
        )
        self.assertIsNone(data["default_provider"])

    @patch("api.views.services.get_media_metadata")
    def test_includes_saved_default_provider(self, mock_get_media_metadata):
        """A saved preference is included, and stays private to its owner."""
        item = Item.objects.create(
            media_id="238",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="Test Movie",
            image="http://example.com/movie.jpg",
        )
        DefaultProvider.objects.create(
            user=self.user,
            item=item,
            provider_id=8,
            provider_name="Netflix",
        )
        other_credentials = {"username": "other", "password": "testpass"}
        other_user = get_user_model().objects.create_user(**other_credentials)
        mock_get_media_metadata.return_value = {"providers": {}}

        response = self.client.get(
            self._url(),
            headers={"Authorization": f"Token {self.user.token}"},
        )
        other_response = self.client.get(
            self._url(),
            headers={"Authorization": f"Token {other_user.token}"},
        )

        self.assertEqual(
            response.json()["default_provider"],
            {"id": 8, "name": "Netflix"},
        )
        self.assertIsNone(other_response.json()["default_provider"])

    @patch("api.views.services.get_media_metadata")
    def test_unset_region_reports_not_configured(self, mock_get_media_metadata):
        """A user who never configured a region gets an empty list, flagged as such."""
        mock_get_media_metadata.return_value = {
            "providers": {
                "US": {
                    "flatrate": [
                        {
                            "provider_id": 8,
                            "provider_name": "Netflix",
                            "logo_path": "/netflix.jpg",
                            "display_priority": 0,
                        },
                    ],
                },
            },
        }

        response = self.client.get(
            self._url(),
            headers={"Authorization": f"Token {self.user.token}"},
        )

        data = response.json()
        self.assertFalse(data["region_configured"])
        self.assertEqual(data["providers"], [])

    @patch("api.views.services.get_media_metadata")
    def test_unknown_tmdb_id_returns_json_not_found(self, mock_get_media_metadata):
        """An unknown tmdb_id surfaces as a JSON 404, not an HTML error page."""
        mock_error = Mock(response=Mock(status_code=404, text="Not Found"))
        mock_get_media_metadata.side_effect = services.ProviderAPIError(
            Sources.TMDB.value,
            mock_error,
        )

        response = self.client.get(
            self._url(),
            headers={"Authorization": f"Token {self.user.token}"},
        )

        self.assertEqual(response.status_code, 404)
        self.assertIn("detail", response.json())

    def test_missing_token_is_unauthorized(self):
        """A request with no Authorization header is rejected."""
        response = self.client.get(self._url())

        self.assertEqual(response.status_code, 401)

    def test_unsupported_media_type_is_not_routed(self):
        """A media_type outside tv/movie doesn't match any route."""
        response = self.client.get(
            "/api/media/anime/1/providers",
            headers={"Authorization": f"Token {self.user.token}"},
        )

        self.assertEqual(response.status_code, 404)


class SetDefaultProviderViewTest(TestCase):
    """Test the PUT /api/media/<media_type>/<tmdb_id>/default-provider endpoint."""

    def setUp(self):
        """Set up an authenticated user with one tracked movie."""
        self.credentials = {"username": "test", "password": "testpass"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        self.item = Item.objects.create(
            media_id="238",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="Test Movie",
            image="http://example.com/movie.jpg",
        )

    def _url(self, media_type="movie", tmdb_id="238"):
        """Build the default-provider URL for a given media type and tmdb id."""
        return reverse(
            "api_default_provider",
            kwargs={"media_type": media_type, "tmdb_id": tmdb_id},
        )

    def _put(self, body=None, **kwargs):
        """PUT to the default-provider endpoint as the authenticated user."""
        headers = {"Authorization": f"Token {self.user.token}"}
        if body is None:
            return self.client.put(self._url(), headers=headers, **kwargs)
        return self.client.put(
            self._url(),
            data=body,
            content_type="application/json",
            headers=headers,
            **kwargs,
        )

    @patch("api.views.services.get_media_metadata")
    def test_sets_default_provider(self, mock_get_media_metadata):
        """A currently-available provider_id is saved."""
        mock_get_media_metadata.return_value = {
            "providers": {"US": {"flatrate": [NETFLIX_PROVIDER, HULU_PROVIDER]}},
        }
        self.user.watch_provider_region = "US"
        self.user.save()

        response = self._put('{"provider_id": 8}')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["default_provider"],
            {"id": 8, "name": "Netflix"},
        )
        saved = DefaultProvider.objects.get(user=self.user, item=self.item)
        self.assertEqual(saved.provider_id, 8)
        self.assertEqual(saved.provider_name, "Netflix")

    @patch("api.views.services.get_media_metadata")
    def test_updates_existing_default_provider(self, mock_get_media_metadata):
        """Setting a new provider_id overwrites the previous choice, not a duplicate."""
        DefaultProvider.objects.create(
            user=self.user,
            item=self.item,
            provider_id=8,
            provider_name="Netflix",
        )
        mock_get_media_metadata.return_value = {
            "providers": {"US": {"flatrate": [NETFLIX_PROVIDER, HULU_PROVIDER]}},
        }
        self.user.watch_provider_region = "US"
        self.user.save()

        response = self._put('{"provider_id": 15}')

        self.assertEqual(
            response.json()["default_provider"],
            {"id": 15, "name": "Hulu"},
        )
        self.assertEqual(DefaultProvider.objects.filter(user=self.user).count(), 1)

    def test_clears_default_provider_with_null_body(self):
        """A JSON null body clears an existing preference."""
        DefaultProvider.objects.create(
            user=self.user,
            item=self.item,
            provider_id=8,
            provider_name="Netflix",
        )

        response = self._put("null")

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()["default_provider"])
        self.assertFalse(
            DefaultProvider.objects.filter(user=self.user, item=self.item).exists(),
        )

    def test_clears_default_provider_with_empty_body(self):
        """An empty PUT body also clears an existing preference."""
        DefaultProvider.objects.create(
            user=self.user,
            item=self.item,
            provider_id=8,
            provider_name="Netflix",
        )

        response = self._put()

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()["default_provider"])

    @patch("api.views.services.get_media_metadata")
    def test_rejects_provider_not_currently_available(self, mock_get_media_metadata):
        """A provider_id absent from the current availability list is rejected."""
        mock_get_media_metadata.return_value = {
            "providers": {"US": {"flatrate": [NETFLIX_PROVIDER]}},
        }
        self.user.watch_provider_region = "US"
        self.user.save()

        response = self._put('{"provider_id": 999}')

        self.assertEqual(response.status_code, 400)
        self.assertFalse(DefaultProvider.objects.filter(user=self.user).exists())

    def test_rejects_malformed_json(self):
        """A malformed JSON body is a clean 400, not an uncaught exception."""
        response = self._put("{not valid json")

        self.assertEqual(response.status_code, 400)

    def test_rejects_non_integer_provider_id(self):
        """A non-integer provider_id is rejected."""
        response = self._put('{"provider_id": "eight"}')

        self.assertEqual(response.status_code, 400)

    def test_untracked_item_returns_not_found(self):
        """A tmdb_id with no matching tracked Item returns 404."""
        response = self.client.put(
            self._url(tmdb_id="999999"),
            headers={"Authorization": f"Token {self.user.token}"},
        )

        self.assertEqual(response.status_code, 404)

    def test_missing_token_is_unauthorized(self):
        """A request with no Authorization header is rejected."""
        response = self.client.put(self._url())

        self.assertEqual(response.status_code, 401)
