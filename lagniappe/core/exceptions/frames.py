"""Traceback frame extraction with entity deduplication for error reports."""

from .constants import FILTER_KEYS, JINJA_GLOBALS_FILTER, SKIP_TYPES
from .utility import safe_repr


def extract_local_variables(tb, max_frames=10):
    """Extract local variables from traceback frames.

    Entity deduplication: The 'entity' passed from auth decorator is often present
    in multiple frames. We track it by its 'key' attribute and:
    - Show full entity in the first frame (initial state from auth)
    - Show full entity in the last frame (state at error)
    - Skip it in middle frames (just show a reference)
    Other variables with 'key' attributes that don't match are shown normally.
    """
    # First pass: collect all frames
    raw_frames = []
    frame_count = 0
    auth_entity_key = None  # Track the key of the entity from auth

    while tb is not None and frame_count < max_frames:
        frame = tb.tb_frame
        filename = frame.f_code.co_filename
        lineno = tb.tb_lineno
        function = frame.f_code.co_name

        # Skip internal Flask/Werkzeug frames and site-packages (includes jinja2 internals)
        if any(
            skip in filename
            for skip in ["werkzeug", "flask/app.py", "flask/ctx.py", "site-packages"]
        ):
            tb = tb.tb_next
            continue

        # Skip compiled Jinja template frames (.html files) - these don't have useful locals
        # But we keep the frames that CALL render_template (those show template args)
        if any(
            filename.endswith(ext) for ext in [".html", ".jinja2", ".jinja", ".htm"]
        ):
            tb = tb.tb_next
            continue

        # Collect frame locals, tracking auth entity by key
        frame_locals = {}
        auth_entity_in_frame = None

        for var_name, value in frame.f_locals.items():
            if var_name in FILTER_KEYS or var_name in JINJA_GLOBALS_FILTER:
                continue
            if var_name.startswith("_"):
                continue
            if isinstance(value, SKIP_TYPES):
                continue

            # Check if this looks like the auth entity (has 'key' attribute)
            # Use try/except because Jinja Undefined objects raise UndefinedError on getattr
            try:
                value_key = getattr(value, "key", None)
            except Exception:
                value_key = None

            if value_key is not None:
                # First frame with a keyed entity - this is likely from auth
                if auth_entity_key is None:
                    auth_entity_key = value_key

                # If this matches the auth entity key, track it separately
                if value_key == auth_entity_key:
                    auth_entity_in_frame = (var_name, value)
                    continue  # Don't add to frame_locals yet

            # Regular variable - wrap in try/except for Jinja Undefined objects
            try:
                frame_locals[var_name] = safe_repr(value)
            except Exception:
                frame_locals[var_name] = f"<Unable to repr: {type(value).__name__}>"

        raw_frames.append(
            {
                "filename": filename,
                "lineno": lineno,
                "function": function,
                "frame_locals": frame_locals,
                "auth_entity": auth_entity_in_frame,  # (var_name, obj) or None
            }
        )

        tb = tb.tb_next
        frame_count += 1

    # Second pass: find first and last frames with the auth entity
    entity_frame_indices = [i for i, f in enumerate(raw_frames) if f["auth_entity"]]
    first_entity_idx = entity_frame_indices[0] if entity_frame_indices else None
    last_entity_idx = entity_frame_indices[-1] if entity_frame_indices else None

    # Build final frames with entity deduplication
    frames_info = []
    for i, frame in enumerate(raw_frames):
        locals_dict = frame["frame_locals"].copy()

        if frame["auth_entity"]:
            var_name, entity_obj = frame["auth_entity"]

            if i == first_entity_idx or i == last_entity_idx:
                # Show full entity in first and last frames
                if first_entity_idx == last_entity_idx:
                    label = ""
                elif i == first_entity_idx:
                    label = "(initial state)\n"
                else:
                    label = "(state at error)\n"
                locals_dict[var_name] = f"{label}{safe_repr(entity_obj)}"
            else:
                # Middle frame - just reference
                locals_dict[var_name] = "<same entity - see first/last frame>"

        frames_info.append(
            {
                "filename": frame["filename"],
                "lineno": frame["lineno"],
                "function": frame["function"],
                "locals": locals_dict,
            }
        )

    return frames_info


def extract_entity_from_frames(frames_info):
    """Look for 'entity' in frame locals and extract its formatted representation.

    Returns the entity from the first frame that has full entity data (not a reference).
    """
    for frame in frames_info:
        entity_val = frame.get("locals", {}).get("entity", "")
        # Check if this is a full entity representation (not just a reference)
        if entity_val and "<see first/last frame" not in entity_val:
            return entity_val
    return None
