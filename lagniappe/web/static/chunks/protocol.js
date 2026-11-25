/*! Third-party licenses: /third-party-licenses.txt */
const POLL_PROTOCOL_VERSION = 1;
const MAX_SUBSCRIPTIONS_PER_REQUEST = 64;
const MAX_TYPE_LENGTH = 32;
const MAX_CHANNEL_LENGTH = 64;
const MAX_KEY_LENGTH = 512;
const MAX_IDENTIFIER_LENGTH = 640;
const MAX_CLIENT_ID_LENGTH = 128;
const MAX_CURSOR_LENGTH = 512;
const MAX_STATE_TOKEN_LENGTH = 128;
const MAX_REVISION = 9007199254740991;
const CHANNELS = ["categories", "forms", "home", "home-notes", "ingress", "messages", "pages", "projects", "starred", "tasks", "tool-reports", "users"];
const DESCRIPTOR_FIELDS = { "channel": ["id", "type", "channel", "revision"], "entity": ["id", "type", "key", "revision"], "ingress": ["id", "type", "key", "revision"], "form-lock": ["id", "type", "key", "revision"], "operation": ["id", "type", "key", "revision"], "document": ["id", "type", "key", "sync_id", "generation", "presence_digest", "revision"] };
const NOTIFICATION_FIELDS = ["generation", "revision", "seed"];
const REQUEST_FIELDS = ["version", "client_id", "subscriptions", "closed_documents"];
const OPTIONAL_REQUEST_FIELDS = ["notification_state"];
const RESULT_FIELDS = ["id", "type", "status", "poll_after_ms"];
const RESULT_MEMBERS = { "changed": ["revision", "payload"], "unchanged": ["revision"], "unavailable": [], "error": [] };

const descriptorFields = Object.values(DESCRIPTOR_FIELDS).flat();
const resultMembers = Object.values(RESULT_MEMBERS).flat();
const pollChannels = new Set(CHANNELS);
class PollContractError extends TypeError {
  constructor(path, reason) {
    super(`${path}: ${reason}`);
    this.name = "PollContractError";
    this.path = path;
    this.reason = reason;
  }
}
function isFieldMap(value) {
  return Boolean(value && typeof value === "object" && !Array.isArray(value));
}
const exactFields = (value, path, required, optional = []) => {
  if (!isFieldMap(value)) {
    throw new PollContractError(path, "type");
  }
  const allowed = /* @__PURE__ */ new Set([...required, ...optional]);
  for (const name of required) {
    if (!Object.hasOwn(value, name)) {
      throw new PollContractError(`${path}.${name}`, "missing");
    }
  }
  for (const name of Object.keys(value)) {
    if (!allowed.has(name)) {
      throw new PollContractError(`${path}.${name}`, "unexpected");
    }
  }
  return value;
};
function boundedString(value, path, maximum, { nullable = false } = {}) {
  if (nullable && value === null) return null;
  if (typeof value !== "string") throw new PollContractError(path, "type");
  if (!value.trim()) throw new PollContractError(path, "blank");
  if (value.length > maximum) throw new PollContractError(path, "limit");
  return value;
}
const integerRevision = (value, path) => {
  if (typeof value !== "number" || !Number.isInteger(value))
    throw new PollContractError(path, "type");
  if (value < 0) throw new PollContractError(path, "state");
  if (value > MAX_REVISION) throw new PollContractError(path, "limit");
  return value;
};
const documentId = (raw, path) => {
  const value = boundedString(raw, path, MAX_KEY_LENGTH);
  if (!value.endsWith(":document")) {
    throw new PollContractError(path, "unsupported");
  }
  return value;
};
const normalizedDescriptor = (value, path = "descriptor") => {
  const raw = exactFields(
    value,
    path,
    ["id", "type", "revision"],
    descriptorFields
  );
  const id = boundedString(raw.id, `${path}.id`, MAX_IDENTIFIER_LENGTH);
  const type = boundedString(
    raw.type,
    `${path}.type`,
    MAX_TYPE_LENGTH
  );
  if (!Object.hasOwn(DESCRIPTOR_FIELDS, type)) {
    throw new PollContractError(`${path}.type`, "unsupported");
  }
  exactFields(raw, path, DESCRIPTOR_FIELDS[type]);
  switch (type) {
    case "channel": {
      const revision = boundedString(
        raw.revision,
        `${path}.revision`,
        MAX_CURSOR_LENGTH,
        { nullable: true }
      );
      const channel = boundedString(
        raw.channel,
        `${path}.channel`,
        MAX_CHANNEL_LENGTH
      );
      if (!pollChannels.has(channel)) {
        throw new PollContractError(`${path}.channel`, "unsupported");
      }
      return { id, type, revision, channel };
    }
    case "operation":
      return {
        id,
        type,
        revision: integerRevision(raw.revision, `${path}.revision`),
        key: boundedString(raw.key, `${path}.key`, MAX_KEY_LENGTH)
      };
    case "document":
      return {
        id,
        type,
        revision: integerRevision(raw.revision, `${path}.revision`),
        key: boundedString(raw.key, `${path}.key`, MAX_KEY_LENGTH),
        sync_id: documentId(raw.sync_id, `${path}.sync_id`),
        generation: boundedString(
          raw.generation,
          `${path}.generation`,
          MAX_STATE_TOKEN_LENGTH,
          { nullable: true }
        ),
        presence_digest: boundedString(
          raw.presence_digest,
          `${path}.presence_digest`,
          MAX_STATE_TOKEN_LENGTH,
          { nullable: true }
        )
      };
    case "form-lock":
      return {
        id,
        type,
        revision: boundedString(
          raw.revision,
          `${path}.revision`,
          MAX_CURSOR_LENGTH
        ),
        key: boundedString(raw.key, `${path}.key`, MAX_KEY_LENGTH)
      };
    default:
      return {
        id,
        type,
        revision: boundedString(
          raw.revision,
          `${path}.revision`,
          MAX_CURSOR_LENGTH,
          { nullable: true }
        ),
        key: boundedString(raw.key, `${path}.key`, MAX_KEY_LENGTH)
      };
  }
};
const normalizedNotificationState = (value, path = "notification_state") => {
  const raw = exactFields(value, path, NOTIFICATION_FIELDS);
  if (typeof raw.seed !== "boolean") {
    throw new PollContractError(`${path}.seed`, "type");
  }
  const generation = boundedString(
    raw.generation,
    `${path}.generation`,
    MAX_STATE_TOKEN_LENGTH,
    { nullable: true }
  );
  const revision = raw.revision === null ? null : integerRevision(raw.revision, `${path}.revision`);
  const cold = raw.seed && generation === null && revision === null;
  const warm = !raw.seed && generation !== null && revision !== null;
  if (cold) return { generation, revision, seed: true };
  if (warm) return { generation, revision, seed: false };
  throw new PollContractError(path, "state");
};
const normalizedRequest = (value) => {
  const raw = exactFields(
    value,
    "request",
    REQUEST_FIELDS,
    OPTIONAL_REQUEST_FIELDS
  );
  if (raw.version !== POLL_PROTOCOL_VERSION) {
    throw new PollContractError("request.version", "unsupported");
  }
  const client_id = boundedString(
    raw.client_id,
    "request.client_id",
    MAX_CLIENT_ID_LENGTH
  );
  if (!Array.isArray(raw.subscriptions)) {
    throw new PollContractError("request.subscriptions", "type");
  }
  if (raw.subscriptions.length > MAX_SUBSCRIPTIONS_PER_REQUEST) {
    throw new PollContractError("request.subscriptions", "limit");
  }
  const identifiers = /* @__PURE__ */ new Set();
  const subscriptions = raw.subscriptions.map((descriptor, index) => {
    const normalized = normalizedDescriptor(
      descriptor,
      `request.subscriptions[${index}]`
    );
    if (identifiers.has(normalized.id)) {
      throw new PollContractError(
        `request.subscriptions[${index}].id`,
        "duplicate"
      );
    }
    identifiers.add(normalized.id);
    return normalized;
  });
  if (!Array.isArray(raw.closed_documents)) {
    throw new PollContractError("request.closed_documents", "type");
  }
  if (raw.closed_documents.length > MAX_SUBSCRIPTIONS_PER_REQUEST) {
    throw new PollContractError("request.closed_documents", "limit");
  }
  const closedIds = /* @__PURE__ */ new Set();
  const closed_documents = raw.closed_documents.map((syncId, index) => {
    const path = `request.closed_documents[${index}]`;
    const normalized = documentId(syncId, path);
    if (closedIds.has(normalized)) {
      throw new PollContractError(path, "duplicate");
    }
    closedIds.add(normalized);
    return normalized;
  });
  const requestBody = {
    version: POLL_PROTOCOL_VERSION,
    client_id,
    subscriptions,
    closed_documents
  };
  if (Object.hasOwn(raw, "notification_state")) {
    requestBody.notification_state = normalizedNotificationState(
      raw.notification_state,
      "request.notification_state"
    );
  }
  return requestBody;
};
const normalizedResult = (value, descriptor, path) => {
  const raw = exactFields(value, path, RESULT_FIELDS, resultMembers);
  if (raw.id !== descriptor.id)
    throw new PollContractError(`${path}.id`, "state");
  if (raw.type !== descriptor.type) {
    throw new PollContractError(`${path}.type`, "state");
  }
  const status = raw.status;
  if (!Object.hasOwn(RESULT_MEMBERS, status)) {
    throw new PollContractError(`${path}.status`, "unsupported");
  }
  if (typeof raw.poll_after_ms !== "number" || !Number.isSafeInteger(raw.poll_after_ms)) {
    throw new PollContractError(`${path}.poll_after_ms`, "type");
  }
  if (raw.poll_after_ms <= 0) {
    throw new PollContractError(`${path}.poll_after_ms`, "state");
  }
  const members = RESULT_MEMBERS[status];
  const carriesRevision = members.includes("revision");
  if (carriesRevision && !Object.hasOwn(raw, "revision")) {
    throw new PollContractError(`${path}.revision`, "missing");
  }
  if (!carriesRevision && Object.hasOwn(raw, "revision")) {
    throw new PollContractError(`${path}.revision`, "unexpected");
  }
  let revision;
  if (carriesRevision) {
    revision = descriptor.type === "operation" || descriptor.type === "document" ? integerRevision(raw.revision, `${path}.revision`) : boundedString(raw.revision, `${path}.revision`, MAX_CURSOR_LENGTH);
  }
  let payload;
  if (members.includes("payload")) {
    if (!Object.hasOwn(raw, "payload")) {
      throw new PollContractError(`${path}.payload`, "missing");
    }
    if (!isFieldMap(raw.payload)) {
      throw new PollContractError(`${path}.payload`, "type");
    }
    payload = raw.payload;
  } else if (Object.hasOwn(raw, "payload")) {
    throw new PollContractError(`${path}.payload`, "unexpected");
  }
  if (payload && descriptor.type === "document") {
    boundedString(
      payload.generation,
      `${path}.payload.generation`,
      MAX_STATE_TOKEN_LENGTH
    );
    const payloadRevision = integerRevision(
      payload.revision,
      `${path}.payload.revision`
    );
    if (payloadRevision !== revision) {
      throw new PollContractError(`${path}.payload.revision`, "state");
    }
    if (Object.hasOwn(payload, "presence_digest")) {
      boundedString(
        payload.presence_digest,
        `${path}.payload.presence_digest`,
        MAX_STATE_TOKEN_LENGTH
      );
    }
  }
  if (payload && descriptor.type === "operation") {
    const payloadRevision = integerRevision(
      payload.revision,
      `${path}.payload.revision`
    );
    if (payloadRevision !== revision || payload.key !== descriptor.key) {
      throw new PollContractError(`${path}.payload`, "state");
    }
  }
  return {
    id: descriptor.id,
    type: descriptor.type,
    status,
    poll_after_ms: raw.poll_after_ms,
    ...carriesRevision ? { revision } : {},
    ...status === "changed" ? { payload } : {}
  };
};

export { MAX_SUBSCRIPTIONS_PER_REQUEST as M, PollContractError as P, normalizedRequest as a, normalizedNotificationState as b, POLL_PROTOCOL_VERSION as c, documentId as d, normalizedResult as e, MAX_CLIENT_ID_LENGTH as f, isFieldMap as i, normalizedDescriptor as n };
