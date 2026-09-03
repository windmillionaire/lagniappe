"""Unit tests for File entity properties.

Heavy persistence (save/delete), ``AttachedToPages`` with real DB keys, and full
Document-AI / cloud upload paths are tracked as planned integration-shaped
stories here and covered in e2e where possible.
"""

from io import BytesIO
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from lagniappe.core.definitions import asset as asset_defs
from lagniappe.core.definitions import LARGE_ASSET_BYTES
from lagniappe.core.definitions.asset import ImageAsset
from lagniappe.core.entities.history import TaskHistory
from lagniappe.core.properties.file_assets import FileAsset
from testing.utility.test_entities import TestEntities


# @matrix file : display-name filename-fallback
@pytest.mark.unit
def test_display_name(get_test_entities):
    """Test DisplayName property returns name if set, otherwise filename without extension."""
    for file in get_test_entities():
        expected = file.test_spec["expected"]

        # Set filename first (needed for fallback)
        file.filename = file.test_spec.get("filename")

        # Set name from test spec (may be null for fallback tests)
        if file.test_spec.get("name"):
            file.name = file.test_spec.get("name")
        else:
            file.db.pop("name")

        assert file.name == expected["name"], (
            f"{file.test_spec['filename']}: name = {file.name}, expected {expected['name']}"
        )


# @matrix file : encoding mimetype property
@pytest.mark.unit
def test_filename_mimetype_encoding(get_test_entities):
    """Test simple DBProperty getters/setters for filename, mimetype, encoding."""
    for file in get_test_entities():
        expected = file.test_spec["expected"]

        file.filename = file.test_spec.get("filename")
        file.mimetype = file.test_spec.get("mimetype")
        if "encoding" in file.test_spec:
            file.encoding = file.test_spec.get("encoding")

        assert file.filename == expected["filename"]
        assert file.mimetype == expected["mimetype"]
        assert file.encoding == expected["encoding"]


# @matrix file : cache summary
@pytest.mark.unit
def test_summary(get_test_entities):
    """Test Summary property with conditional description cache projection."""
    for file in get_test_entities():
        expected = file.test_spec["expected"]

        file.summary = file.test_spec.get("summary")

        # Set summarize.search option
        file.properties.summarize.search = file.test_spec.get("summarize_search", False)

        assert file.summary == expected["summary"]
        assert file.properties.summary.cache_value == expected.get("cache_value")


# @matrix file : cache description
@pytest.mark.unit
def test_file_description_form_field_populates_search_cache():
    """File info's description field should save to the searchable cache desc."""
    file = TestEntities.get("FILE", {"filename": "permit-packet.pdf"})
    description = "<strong>Generated permit packet description.</strong>"

    file.update({"name": "Permit packet", "description": description})

    assert file.summary == "Generated permit packet description."
    assert file.to_cache["desc"] == "Generated permit packet description."


# @pairs ai-report:pre-execution files:search-visibility
@pytest.mark.unit
def test_report_file_is_searchable_only_after_workspace_attachment():
    user = TestEntities.get("USER", {"name": "Report owner", "hash": "reportowner"})
    file = TestEntities.get(
        "FILE",
        {"filename": "staged-evidence.pdf", "hash": "stagedevidence"},
    )
    file.report_user = user

    assert file.searchable is False

    page = TestEntities.get("PAGE", {"name": "Evidence Page", "hash": "evidencepage"})
    file.db["pages"] = [page.key]

    assert file.searchable is True


# @matrix file : option-preservation update
@pytest.mark.unit
def test_file_update_preserves_processing_options_when_controls_absent():
    """File info saves should not clear search flags when option controls are absent."""
    file = TestEntities.get("FILE", {"filename": "permit-packet.pdf"})
    file.properties.extract.enabled = True
    file.properties.extract.search = True
    file.properties.summarize.enabled = True
    file.properties.summarize.search = True

    file.update({"name": "Permit packet", "description": "Updated description."})

    assert file.properties.extract.enabled is True
    assert file.properties.extract.search is True
    assert file.properties.summarize.enabled is True
    assert file.properties.summarize.search is True


# @matrix ai file : large-file metadata mimetype permissions uri
@pytest.mark.unit
def test_file_to_ai_exports_metadata_and_uri_to_ai():
    user = SimpleNamespace(
        is_authenticated=True,
        is_owner=True,
        has_permission=lambda *_args, **_kwargs: True,
    )
    asset = SimpleNamespace(
        uri="gs://private-bucket/permit-packet.pdf",
        size=4096,
        large=False,
    )
    file = TestEntities.get(
        "FILE",
        {
            "name": "Permit Packet",
            "hash": "permit-file",
            "assets": {"file": asset},
        },
    )
    file.filename = "permit-packet.pdf"
    file.mimetype = "application/pdf"
    file.summary = "Permit application packet."

    ai_data = file.to_ai(user)

    assert ai_data["hash"] == "hash:permit-file"
    assert "id" not in ai_data
    assert ai_data["display_name"] == "Permit Packet"
    assert ai_data["filename"] == "permit-packet.pdf"
    assert ai_data["mimetype"] == "application/pdf"
    assert ai_data["summary"] == "Permit application packet."
    assert file.size == 4096
    assert ai_data["large"] is False
    assert ai_data["permissions"] == {
        "can_view": True,
        "can_edit": True,
        "can_create": True,
    }
    assert "name" not in ai_data
    assert "file_name" not in ai_data
    assert "size" not in ai_data
    assert file.properties.file.uri_to_ai == {
        "uri": "gs://private-bucket/permit-packet.pdf",
        "mime_type": "application/pdf",
    }

    file.mimetype = "application/octet-stream"

    assert file.properties.file.uri_to_ai is None


# @matrix file : asset-metadata large-file size
@pytest.mark.unit
def test_file_size_and_large_use_asset_metadata():
    stored_size = asset_defs.LARGE_ASSET_BYTES + 1
    asset = SimpleNamespace(
        path="large.pdf",
        visibility=SimpleNamespace(value="private"),
        size=stored_size,
        large=True,
    )
    file = TestEntities.get(
        "FILE",
        {
            "name": "Large file",
            "hash": "large-file-metadata",
            "assets": {"file": asset},
        },
    )

    assert file.size == stored_size
    assert file.large is True


# @matrix file : html-preview text-asset
@pytest.mark.unit
def test_as_html(get_test_entities):
    """Test AsHTML property converts text to HTML using the focused helper."""
    with patch("lagniappe.core.properties.file_assets.file_html.htmlize") as mock_htmlize:
        for file in get_test_entities():
            expected = file.test_spec["expected"]

            # Set up mock return value
            mock_htmlize.return_value = expected.get("html")

            # Set text asset if provided
            if file.test_spec.get("has_text"):
                file.properties.text._value = True
                file.properties.text._asset = file.test_spec.get("text_content")

            result = file.html

            if file.test_spec.get("has_text"):
                mock_htmlize.assert_called_once()
            assert result == expected.get("html")

            mock_htmlize.reset_mock()


# @matrix file : fallback html-preview text-asset
@pytest.mark.unit
def test_text_asset_falls_back_to_original_text_file():
    """TextAsset should treat uploaded text files as available text content."""
    file_asset = SimpleNamespace(
        size=len("# Markdown Content"),
        text=lambda: "# Markdown Content",
    )
    file = TestEntities.get("FILE", {"filename": "notes.md", "assets": {"file": file_asset}})
    file.mimetype = "text/markdown"
    file.encoding = "utf-8"

    with patch("lagniappe.core.properties.file_assets.file_html.htmlize") as mock_htmlize:
        mock_htmlize.return_value = "<h1>Markdown Content</h1>"

        assert file.properties.text.value is True
        assert file.properties.text.asset == "# Markdown Content"
        assert file.properties.text.markup == "<h1>Markdown Content</h1>"
        assert file.html == "<h1>Markdown Content</h1>"


# @pair file:text-asset
@pytest.mark.unit
def test_text_asset_skips_oversized_original_before_download():
    file_asset = SimpleNamespace(
        size=LARGE_ASSET_BYTES + 1,
        text=lambda: (_ for _ in ()).throw(
            AssertionError("oversized text must not be downloaded")
        ),
    )
    file = TestEntities.get(
        "FILE",
        {"filename": "oversized.txt", "assets": {"file": file_asset}},
    )
    file.mimetype = "text/plain"
    file.encoding = "utf-8"

    assert file.properties.text.asset is None
    assert file.properties.text.markup is None


# @matrix file : extractable mimetype text-asset
@pytest.mark.unit
def test_text_asset_extractable_only_for_non_text_document_ai_mimetypes():
    """Only non-text OCR-supported mimetypes should be considered extractable."""
    pdf = TestEntities.get("FILE", {"filename": "scan.pdf"})
    pdf.mimetype = "application/pdf"

    markdown = TestEntities.get(
        "FILE", {"filename": "notes.md", "assets": {"file": SimpleNamespace(text=lambda: "hello")}}
    )
    markdown.mimetype = "text/markdown"
    markdown.encoding = "utf-8"

    assert pdf.properties.text.extractable is True
    assert markdown.properties.text.extractable is False


# @matrix file : extract process-complete text-asset
@pytest.mark.unit
def test_extract_update_completes_immediately_for_text_files():
    """Enabling extract on a text file should complete without async work."""
    file = TestEntities.get(
        "FILE",
        {
            "filename": "notes.md",
            "assets": {"file": SimpleNamespace(text=lambda: "# hello")},
        },
    )
    file.mimetype = "text/markdown"
    file.encoding = "utf-8"

    file.properties.extract.update({"enable-extract": "on"})

    assert file.properties.extract.enabled is True
    assert file.properties.extract.complete is True
    assert file.properties.extract.status == "Text extraction complete."
    assert file.properties.extract.error is None


# @matrix file : extract process update
@pytest.mark.unit
def test_extract_process(get_test_entities):
    """Test Extract ProcessProperty attributes and extract kickoff behavior."""
    for file in get_test_entities():
        expected = file.test_spec["expected"]

        # Set initial attributes
        file.properties.extract.enabled = file.test_spec.get("enabled", False)
        file.properties.extract.search = file.test_spec.get("search", False)

        assert file.properties.extract.enabled == expected["enabled"]
        assert file.properties.extract.search == expected["search"]

        # Test update method if status provided
        if "update_status" in file.test_spec:
            with patch("lagniappe.core.properties.file_options.get_file_text") as extract:
                def _complete(entity, *, dispatch):
                    assert dispatch is False
                    entity.properties.extract.complete = True
                    entity.properties.extract.status = expected["status"]
                    return entity.properties.extract

                extract.side_effect = _complete
                file.properties.extract.update(
                    {
                        "enable-extract": "on",
                        "search-text": "on"
                        if file.test_spec.get("search")
                        else None,
                    }
                )

            extract.assert_called_once_with(file, dispatch=False)
            assert file.properties.extract.complete == expected.get("complete", False)
            assert file.properties.extract.enabled is True


# @matrix file : process summarize update
@pytest.mark.unit
def test_summarize_process(get_test_entities):
    """Test Summarize ProcessProperty attributes and summarize kickoff behavior."""
    for file in get_test_entities():
        expected = file.test_spec["expected"]

        # Set initial attributes
        file.properties.summarize.enabled = file.test_spec.get("enabled", False)
        file.properties.summarize.search = file.test_spec.get("search", False)
        file.properties.summarize.retrieval_terms = ["person", "topic"]

        assert file.properties.summarize.enabled == expected["enabled"]
        assert file.properties.summarize.search == expected["search"]
        assert file.properties.summarize.retrieval_terms == ["person", "topic"]

        if "update_status" in file.test_spec:
            with patch("lagniappe.core.properties.file_options.summarize_file") as summarize:
                summarize.return_value = file.properties.summarize
                file.properties.summarize.update(
                    {
                        "enable-summarize": "on",
                        "search-summary": "on"
                        if file.test_spec.get("search")
                        else None,
                    }
                )

            summarize.assert_called_once_with(file, dispatch=False)
            assert file.properties.summarize.enabled is True


# @matrix file : summarize update
@pytest.mark.unit
def test_summarize_update_uses_enable_field_name():
    """File-info summarize enablement should make generated descriptions searchable."""
    file = TestEntities.get("FILE", {"filename": "document.pdf"})

    with patch("lagniappe.core.properties.file_options.summarize_file") as summarize:
        file.properties.summarize.update({"enable-summarize": "on"})

    assert file.properties.summarize.enabled is True
    assert file.properties.summarize.search is True
    summarize.assert_called_once_with(file, dispatch=False)


# @matrix file : search-opt-in summarize update
@pytest.mark.unit
def test_summarize_update_upload_search_summary_remains_opt_in():
    """Upload summarize search should still follow the search-summary checkbox."""
    file = TestEntities.get("FILE", {"filename": "document.pdf"})

    with patch("lagniappe.core.properties.file_options.summarize_file") as summarize:
        file.properties.summarize.update({"summarize": "on"})

    assert file.properties.summarize.enabled is True
    assert file.properties.summarize.search is False
    summarize.assert_called_once_with(file, dispatch=False)

    indexed_file = TestEntities.get("FILE", {"filename": "document.pdf"})
    with patch("lagniappe.core.properties.file_options.summarize_file"):
        indexed_file.properties.summarize.update(
            {
                "summarize": "on",
                "search-summary": "on",
            }
        )

    assert indexed_file.properties.summarize.search is True


# @matrix deferred-jobs file : deferred-dispatch extraction-follow-up post-save-dispatch summary-first
@pytest.mark.unit
def test_file_processing_dispatches_summary_before_extraction():
    """Selecting both operations queues one summary with extraction as its successor."""
    file = TestEntities.get("FILE", {"filename": "photo.png"})

    def prepare_extract(entity, *, dispatch):
        assert entity is file
        assert dispatch is False
        entity.properties.extract.status = "Extracting text..."
        return entity.properties.extract

    def prepare_summary(entity, *, dispatch):
        assert entity is file
        assert dispatch is False
        entity.properties.summarize.status = "Summarizing file..."
        return entity.properties.summarize

    with (
        patch(
            "lagniappe.core.properties.file_options.get_file_text",
            side_effect=prepare_extract,
        ) as extract,
        patch(
            "lagniappe.core.properties.file_options.summarize_file",
            side_effect=prepare_summary,
        ) as summarize,
    ):
        file.update(
            {
                "extract": "on",
                "summarize": "on",
            }
        )

    extract.assert_called_once_with(file, dispatch=False)
    summarize.assert_called_once_with(file, dispatch=False)
    assert file.properties.extract.status == "Waiting for file summary..."

    with (
        patch(
            "lagniappe.core.properties.file_options.get_file_text"
        ) as start_extract,
        patch(
            "lagniappe.core.properties.file_options.summarize_file",
            return_value=file.properties.summarize,
        ) as start_summary,
    ):
        result = file.dispatch_pending_processing()
        duplicate = file.dispatch_pending_processing()

    assert result is file.properties.summarize
    assert duplicate is None
    start_summary.assert_called_once_with(
        file,
        parameters={"extract_after_summary": True},
    )
    start_extract.assert_not_called()


# @matrix file : summarize update
@pytest.mark.unit
def test_summarize_update_starts_without_browser_routing_identity():
    """Summarization starts without any browser-specific client identity."""
    file = TestEntities.get("FILE", {"filename": "document.pdf"})

    with patch("lagniappe.core.properties.file_options.summarize_file") as summarize:
        file.properties.summarize.update({"enable-summarize": "on"})

    summarize.assert_called_once_with(file, dispatch=False)
    assert file.properties.summarize.enabled is True


# @matrix file : asset mimetype preview
@pytest.mark.unit
def test_preview_url_when_mimetype_supported_and_file_present():
    """Preview returns file URL when mimetype is in PREVIEW_MIMETYPES and asset exists."""
    file_asset = SimpleNamespace(url="https://example.test/signed-file")
    file = TestEntities.get(
        "FILE", {"filename": "shot.png", "assets": {"file": file_asset}}
    )
    file.mimetype = "image/png"

    assert file.preview == "https://example.test/signed-file"


# @matrix file : mimetype preview unsupported
@pytest.mark.unit
def test_preview_none_when_mimetype_not_supported():
    """Preview is None when mimetype is not eligible for inline preview."""
    file_asset = SimpleNamespace(url="https://example.test/blob")
    file = TestEntities.get(
        "FILE", {"filename": "data.bin", "assets": {"file": file_asset}}
    )
    file.mimetype = "application/octet-stream"

    assert file.preview is None


# @matrix file : missing-asset preview
@pytest.mark.unit
def test_preview_none_when_no_file_asset():
    """Preview is None when preview mimetype is set but file asset is missing."""
    file = TestEntities.get("FILE", {"filename": "orphan.png"})
    file.mimetype = "image/png"

    assert file.preview is None


# @matrix file : extract options summarize
@pytest.mark.unit
def test_options(get_test_entities):
    """Test Options property returns combined extract/summarize options."""
    for file in get_test_entities():
        expected = file.test_spec["expected"]

        # Set up extract and summarize options
        file.properties.extract.enabled = file.test_spec.get("extract_enabled", False)
        file.properties.summarize.enabled = file.test_spec.get(
            "summarize_enabled", False
        )

        options = file.options

        assert options is not None
        assert ("extract" in options) == expected["has_extract"]
        assert ("summarize" in options) == expected["has_summarize"]


# @matrix file : asset-lifecycle encoding metadata upload
@pytest.mark.unit
def test_uploaded_file_story_records_metadata_before_asset_save():
    class FakeFile:
        def __init__(self, filename):
            self.filename = filename
            self.mimetype = ""
            self.encoding = None
            self.assets = {}
            self.saved = []
            self.deleted = []

        def get_asset(self, name):
            return self.assets.get(name)

        def save_asset(self, content, name, asset_type):
            self.saved.append(
                {
                    "content": content,
                    "name": name,
                    "asset_type": asset_type,
                    "mimetype": self.mimetype,
                    "encoding": self.encoding,
                }
            )
            asset = SimpleNamespace(url=f"/assets/{name}", uri=f"gs://bucket/{name}")
            self.assets[name] = asset
            return asset

        def delete_asset(self, name):
            self.deleted.append(name)
            self.assets.pop(name, None)

    text_file = FakeFile("notes.txt")
    text_asset = FileAsset(entity=text_file, user=object())
    text_upload = SimpleNamespace(content_type="text/plain")

    with (
        patch(
            "lagniappe.core.properties.file_assets.file_utility.determine_mimetype",
            return_value="text/plain",
        ) as determine_mimetype,
        patch(
            "lagniappe.core.properties.file_assets.file_utility.determine_encoding",
            return_value="utf-8",
        ) as determine_encoding,
    ):
        text_asset.value = text_upload

    determine_mimetype.assert_called_once_with(
        text_upload,
        "notes.txt",
        "text/plain",
        None,
    )
    determine_encoding.assert_called_once_with(text_upload)
    assert text_file.mimetype == "text/plain"
    assert text_file.encoding == "utf-8"
    assert text_file.saved == [
        {
            "content": text_upload,
            "name": "file",
            "asset_type": "file",
            "mimetype": "text/plain",
            "encoding": "utf-8",
        }
    ]
    assert text_asset.url == "/assets/file"
    assert text_asset.uri == "gs://bucket/file"
    assert text_asset.image is None

    image_file = FakeFile("photo.png")
    image_asset = FileAsset(entity=image_file, user=object())
    image_upload = SimpleNamespace(content_type="image/png")

    with (
        patch(
            "lagniappe.core.properties.file_assets.file_utility.determine_mimetype",
            return_value="image/png",
        ),
        patch("lagniappe.core.properties.file_assets.file_utility.determine_encoding")
        as determine_encoding,
    ):
        image_asset.value = image_upload

    determine_encoding.assert_not_called()
    assert image_asset.url == "/assets/file"
    assert image_asset.preview == "/assets/file"
    assert image_asset.image == "/assets/file"
    assert image_asset.uri == "gs://bucket/file"

    class TextUpload(BytesIO):
        def __init__(self, content, content_type):
            super().__init__(content)
            self.content_type = content_type

    charset_file = FakeFile("notes.txt")
    charset_asset = FileAsset(entity=charset_file, user=object())
    charset_upload = TextUpload(b"cafe notes", "Text/Plain; charset=utf-8")

    charset_asset.value = charset_upload

    assert charset_file.mimetype == "text/plain"
    assert charset_file.encoding == "utf-8"
    assert charset_upload.lagniappe_content_type == "text/plain"

    vcard_file = FakeFile("person.vcf")
    vcard_asset = FileAsset(entity=vcard_file, user=object())
    vcard_upload = TextUpload(b"BEGIN:VCARD\nFN:Avery Rowan\nEND:VCARD\n", "text/vcard")

    vcard_asset.value = vcard_upload

    assert vcard_file.mimetype == "text/vcard"
    assert vcard_file.encoding == "utf-8"
    assert vcard_upload.lagniappe_content_type == "text/vcard"


# @matrix file storage : direct-upload large-video metadata
@pytest.mark.unit
def test_direct_upload_file_asset_sniffs_generic_video_from_sample_without_full_read():
    class FakeFile:
        filename = "large-video.mp4"
        mimetype = ""
        encoding = None

        def __init__(self):
            self.assets = {}
            self.saved = []

        def get_asset(self, name):
            return self.assets.get(name)

        def save_asset(self, content, name, asset_type):
            asset = SimpleNamespace(url=f"/assets/{name}", uri=f"gs://bucket/{name}")
            self.saved.append(
                {
                    "content": content,
                    "name": name,
                    "asset_type": asset_type,
                    "mimetype": self.mimetype,
                    "encoding": self.encoding,
                }
            )
            self.assets[name] = asset
            return asset

    class DirectVideoUpload:
        lagniappe_direct_upload = True
        content_type = "application/octet-stream"

        def __init__(self):
            self.samples = []

        def read_sample(self, size):
            self.samples.append(size)
            return b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom"

        def seek(self, *_args, **_kwargs):
            raise AssertionError("direct-upload finalization must not seek full object")

        def read(self, *_args, **_kwargs):
            raise AssertionError("direct-upload finalization must not read full object")

    file = FakeFile()
    upload = DirectVideoUpload()
    asset = FileAsset(entity=file, user=object())

    asset.value = upload

    assert upload.samples == [8192]
    assert file.mimetype == "video/mp4"
    assert file.encoding is None
    assert file.saved == [
        {
            "content": upload,
            "name": "file",
            "asset_type": "file",
            "mimetype": "video/mp4",
            "encoding": None,
        }
    ]


# @matrix file storage : asset-uri bucket-prefix public-url
@pytest.mark.unit
def test_asset_uri_and_public_url_include_bucket_prefix(monkeypatch):
    monkeypatch.setattr(asset_defs, "BUCKET_PREFIX", "test-")
    monkeypatch.setattr(asset_defs, "PRIVATE_BUCKET", "private-bucket")
    monkeypatch.setattr(asset_defs, "PUBLIC_BUCKET", "public-bucket")

    entity = SimpleNamespace(hash="asset123", key=None)
    private_asset = asset_defs.FileAsset(name="file", entity=entity)
    private_asset.content_type = "application/pdf"

    public_asset = asset_defs.FileAsset(name="file", entity=entity)
    public_asset.content_type = "application/pdf"
    public_asset.visibility = "public"

    assert private_asset.uri == "gs://test-private-bucket/asset123_file.pdf"
    assert public_asset.uri == "gs://test-public-bucket/asset123_file.pdf"
    assert (
        public_asset.url
        == "https://storage.googleapis.com/test-public-bucket/asset123_file.pdf"
    )


# @matrix file storage : asset-size large-asset
@pytest.mark.unit
def test_file_asset_definition_records_size_and_large_flag(monkeypatch):
    entity = SimpleNamespace(hash="asset123", key=None)
    asset = asset_defs.FileAsset(name="file", entity=entity)
    asset.content_type = "application/pdf"
    upload = BytesIO(b"pdf")
    stored_size = asset_defs.LARGE_ASSET_BYTES + 1

    with patch(
        "lagniappe.core.definitions.asset.database_assets.save_file",
        return_value=SimpleNamespace(size=stored_size),
    ):
        assert asset.save(upload) is True

    assert asset.size == stored_size
    assert asset.large is True
    assert asset.definition == {
        "type": "file",
        "path": "asset123_file.pdf",
        "size": stored_size,
        "large": True,
    }

    existing = asset_defs.FileAsset(
        {
            "type": "file",
            "path": "asset123_file.pdf",
            "size": 1024,
            "large": False,
        },
        name="file",
        entity=entity,
    )
    assert existing.size == 1024
    assert existing.large is False


@pytest.mark.unit
def test_file_asset_direct_upload_uses_storage_copy_without_seek_or_read():
    entity = SimpleNamespace(hash="asset123", key=None)
    asset = asset_defs.FileAsset(name="file", entity=entity)
    asset.content_type = "application/pdf"

    class DirectUpload:
        lagniappe_direct_upload = True
        filename = "large.pdf"

        def seek(self, *_args):
            raise AssertionError("storage copy must not seek the source")

        def read(self):
            raise AssertionError("storage copy must not read the source")

    upload = DirectUpload()
    with patch(
        "lagniappe.core.definitions.asset.database_assets.save_file",
        return_value=SimpleNamespace(size=LARGE_ASSET_BYTES + 1),
    ) as save_file:
        assert asset.save(upload) is True

    save_file.assert_called_once_with(
        upload,
        "asset123_file.pdf",
        "application/pdf",
        "private",
    )
    assert asset.large is True


# @matrix file storage : private-url shared-asset-path
@pytest.mark.unit
def test_private_asset_url_uses_asset_name_for_shared_storage_path(monkeypatch):
    monkeypatch.setattr(
        asset_defs.database_get,
        "urlsafe_key",
        lambda key: "history-key",
    )
    entity = SimpleNamespace(hash="history456", key="history-key")
    asset = asset_defs.FileAsset(
        {
            "type": "image",
            "path": "task123_task-signature-field.png",
        },
        name="task-signature-field",
        entity=entity,
    )

    assert asset.url == "/assets/history-key/task-signature-field.png"


# @matrix file storage : asset-extension mimetype
@pytest.mark.unit
def test_text_plain_asset_uses_txt_extension():
    """Text/plain storage paths should use a familiar .txt extension."""
    entity = SimpleNamespace(hash="assettext", key=None)
    asset = asset_defs.FileAsset(name="file", entity=entity)
    asset.content_type = "text/plain"

    assert asset.path == "assettext_file.txt"


# @matrix file : asset-extension mimetype upload
@pytest.mark.unit
def test_file_asset_detects_mislabeled_png_upload():
    """Magic-byte detection corrects pasted images mislabeled by the browser."""

    class Upload(BytesIO):
        content_type = "text/plain"

    class FakeFile:
        filename = "paste.txt"
        mimetype = ""
        encoding = None
        hash = "pasteimg"
        key = None

        def get_asset(self, _name):
            return None

        def save_asset(self, content, name, _asset_type):
            asset = asset_defs.FileAsset(name=name, entity=self)
            asset.content_type = getattr(content, "lagniappe_content_type", None)
            return asset

        def delete_asset(self, _name):
            pass

    upload = Upload(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)
    file = FakeFile()
    asset = FileAsset(entity=file, user=object())

    asset.value = upload

    assert file.mimetype == "image/png"
    assert upload.lagniappe_content_type == "image/png"
    assert asset.value.path == "pasteimg_file.png"


# @matrix file : content-type image
@pytest.mark.unit
def test_image_asset_content_type_falls_back_without_recursing():
    """New image assets with no upload mimetype should still get a path."""
    entity = SimpleNamespace(hash="imgasset")
    asset = ImageAsset(name="public_image", entity=entity)

    assert asset.content_type == "image/jpeg"
    assert asset.path == "imgasset_public_image.jpeg"

    png_asset = ImageAsset(
        {"path": "imgasset_public_image.png"},
        name="public_image",
        entity=entity,
    )
    assert png_asset.content_type == "image/png"


# @matrix file : attached-pages permissions
@pytest.mark.unit
def test_uploaded_file_story_lists_pages_that_reference_it():
    file = TestEntities.get("FILE", {"filename": "linked.pdf", "hash": "linkedfile"})
    visible = TestEntities.get("PAGE", {"name": "Visible Page", "hash": "vispage"})
    hidden = TestEntities.get("PAGE", {"name": "Hidden Page", "hash": "hiddenpage"})
    hidden.allowed = lambda *_args, **_kwargs: False
    file.db["pages"] = [visible.key, hidden.key]
    file.properties.pages.attach({visible.key: visible, hidden.key: hidden})

    pages = file.properties.pages.value
    again = file.properties.pages.value
    assert pages == [visible, hidden]
    assert again is pages
    assert file.properties.pages.column_value == [visible.reference_details]


# @matrix file : attached-tasks badges permissions references reverse-links task-history
@pytest.mark.unit
def test_file_reverse_task_links_drive_permissions_and_references():
    parent = TestEntities.get("PAGE", {"name": "Parent", "hash": "pgfile1"})
    task = TestEntities.get(
        "TASK",
        {"name": "Task", "hash": "tskfile1"},
        page=parent,
    )
    history = TaskHistory(testing=True)
    history._key = "histfile1"
    history.page = parent
    history.task = task

    file = TestEntities.get("FILE", {"filename": "linked.pdf", "hash": "filetask"})
    file.tasks = [task, history]

    assert file.has_references is True
    assert set(file.required) == {"filetask", "models", "pgfile1"}
    assert file.linked_tasks == [task]

    file.properties.tasks.remove(task)
    assert file.has_references is True
    assert file.linked_tasks == [task]

    file.properties.tasks.remove(history)
    assert file.has_references is False
    assert file.linked_tasks == []
