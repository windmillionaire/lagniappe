"""Shared report contracts independent of properties and AI orchestration."""

# External API proposals are bounded; web and email proposals have no such cap.
MAX_PROPOSAL_ACTIONS = 100

# Shared by external contracts and transactional upload/Plan-operation identities.
UPLOAD_BATCH_ID_PATTERN = r"^[A-Za-z0-9_-]{16,128}$"
