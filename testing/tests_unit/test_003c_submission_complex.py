import pytest

from lagniappe.core.properties.form_special import Signature


class _FakeAsset:
    def __init__(self, body="image-body"):
        self.body = body

    @property
    def url(self):
        return f"https://test.example/{self.body}"

    def get(self):
        return self.body


class _FakeEntity:
    entity_kind = "page"

    def __init__(self, asset=None):
        self.asset = asset
        self.saved = []
        self.deleted = []

    def get_asset(self, name):
        return self.asset

    def save_asset(self, content, name, asset_type):
        asset = _FakeAsset(content)
        self.asset = asset
        self.saved.append((content, name, asset_type))
        return asset

    def delete_asset(self, name):
        self.asset = None
        self.deleted.append(name)


def _signature(entity):
    return Signature(
        {"id": "signature-signop", "type": "signature", "title": "Signature"},
        entity=entity,
        user=object(),
    )


# @matrix status : ai-value column computed condition-matching
@pytest.mark.unit
def test_submission_status(get_test_entities, get_schema, test_submission_values):
    """Test Status field - computed from other fields' values."""
    for entity in get_test_entities():
        entity.form.schema = get_schema(entity.test_spec["form"]["schema"])
        test_submission_values(entity)


# @matrix signature : asset-lifecycle db-value
@pytest.mark.unit
def test_signature_field_asset_lifecycle_saves_and_clears_image():
    entity = _FakeEntity()
    field = _signature(entity)
    image = object()

    field.validate_submission(image)

    assert field.value is entity.asset
    assert field.asset is image
    assert field.db_value == "signature-signop"
    assert entity.saved == [(image, "signature-signop", "image")]
    assert entity.deleted == []

    field.validate_submission("signature-signop")

    assert entity.saved == [(image, "signature-signop", "image")]
    assert field.db_value == "signature-signop"

    field.validate_submission(None)

    assert field.value is None
    assert field.asset is None
    assert field.db_value is None
    assert entity.deleted == ["signature-signop"]


# @matrix signature : ai-value column filter-value form-value sort
@pytest.mark.unit
def test_signature_field_projections_reflect_asset_presence():
    empty = _signature(_FakeEntity())

    assert empty.value is None
    assert empty.db_value is None
    assert empty.form_value is None
    assert empty.filter_value is False
    assert empty.ai_value is False
    assert empty.column_value is None
    assert empty.sort_value is False

    asset = _FakeAsset("saved-signature")
    present = _signature(_FakeEntity(asset=asset))

    assert present.value is asset
    assert present.db_value == "signature-signop"
    assert present.form_value == "https://test.example/saved-signature"
    assert present.filter_value is True
    assert present.ai_value is True
    assert present.column_value == "https://test.example/saved-signature"
    assert present.sort_value is True
