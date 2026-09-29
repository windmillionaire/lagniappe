class ResourceEnumMixin:
    """Share resource lookup and lazy creation across entity definition enums."""

    def get(self, user, create=True):
        from testing.utility.e2e_resources import resolve_resource
        return resolve_resource(self, user, create)
