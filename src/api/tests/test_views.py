"""Tests for the read-only JSON API views."""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from app.models import TV, Item, MediaTypes, Movie, Sources, Status


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
