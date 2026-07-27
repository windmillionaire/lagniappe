from lagniappe.core.entities import Entities

from .core import SiteResource


class Group(SiteResource):
    _permissions_form = None

    def create(self):
        if self.definition.public:
            group = Entities.PUBLIC_GROUP.create()
        else:
            group = Entities.USER_GROUP.create(self.definition.name)

        if self.definition.permission_definition:
            from testing.definitions import Permissions

            p = Permissions[self.definition.permission_definition].get(self.user)
            group.db["permissions"] = p.permissions

        group.save()
        self.entity = group
        return self

    @property
    def permissions_form(self):
        if not self._permissions_form:
            self._permissions_form = self.user.locate(f"[data-key='{self.key}']")
        return self._permissions_form

    @permissions_form.setter
    def permissions_form(self, value):
        self._permissions_form = value
