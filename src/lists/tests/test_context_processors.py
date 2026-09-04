from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory, TestCase

from lists.context_processors import pinned_lists
from lists.models import CustomList, CustomListPin


class PinnedListsContextProcessorTests(TestCase):
    """Tests for the pinned_lists context processor."""

    def setUp(self):
        """Create a user and some lists."""
        self.factory = RequestFactory()
        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        self.list_a = CustomList.objects.create(name="A List", owner=self.user)
        self.list_b = CustomList.objects.create(name="B List", owner=self.user)

    def test_anonymous_user_gets_empty_list(self):
        """Test that an unauthenticated request gets no pinned lists."""
        request = self.factory.get("/")
        request.user = AnonymousUser()
        self.assertEqual(pinned_lists(request), {"pinned_lists": []})

    def test_no_pins(self):
        """Test that a user with no pins gets an empty list."""
        request = self.factory.get("/")
        request.user = self.user
        self.assertEqual(pinned_lists(request), {"pinned_lists": []})

    def test_returns_pinned_lists_oldest_first(self):
        """Test that pinned lists are ordered by pin time, oldest first."""
        CustomListPin.objects.create(user=self.user, custom_list=self.list_b)
        CustomListPin.objects.create(user=self.user, custom_list=self.list_a)

        request = self.factory.get("/")
        request.user = self.user
        result = pinned_lists(request)["pinned_lists"]

        self.assertEqual(result, [self.list_b, self.list_a])

    def test_only_returns_current_users_pins(self):
        """Test that another user's pins aren't included."""
        other_credentials = {"username": "other", "password": "12345"}
        other_user = get_user_model().objects.create_user(**other_credentials)
        CustomListPin.objects.create(user=other_user, custom_list=self.list_a)

        request = self.factory.get("/")
        request.user = self.user
        self.assertEqual(pinned_lists(request), {"pinned_lists": []})
