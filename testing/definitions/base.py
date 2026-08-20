class ResourceEnumMixin:
    """Share resource lookup and lazy creation across entity definition enums."""

    def get(self, user, create=True):
        resource = self.value
        resource.user = user
        if not resource.entity and create:
            return resource.create()
        return resource
