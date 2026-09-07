"""Models for the read/write JSON API."""

from django.conf import settings
from django.db import models

from app.models import Item


class DefaultProvider(models.Model):
    """A user's saved default streaming provider for a tracked title."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    item = models.ForeignKey(Item, on_delete=models.CASCADE)
    provider_id = models.PositiveIntegerField(help_text="TMDB watch-provider id")
    provider_name = models.CharField(max_length=100)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        """Meta options for the model."""

        constraints = [
            models.UniqueConstraint(
                fields=["user", "item"],
                name="%(app_label)s_defaultprovider_unique_user_item",
            ),
        ]

    def __str__(self):
        """Return a readable label for the preference."""
        return f"{self.user} -> {self.item.title}: {self.provider_name}"
