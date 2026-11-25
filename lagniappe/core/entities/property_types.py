"""Static interfaces for lazy property registries, checked against live entities in unit tests.

Persistent entity modules import these types only during type checking.
Runtime construction, registration, and cache lookup stay in EntityProperties.
"""

from ..properties import (
    activity,
    ai_report_input,
    ai_report_process,
    ai_report_proposal,
    ai_report_result,
    category,
    common_assets,
    common_entity,
    common_related,
    deferred_job_dispatch,
    deferred_job_lifecycle,
    deferred_job_lock,
    deferred_job_request,
    file_assets,
    file_entity,
    file_ingress,
    file_options,
    file_related,
    filter,
    form,
    form_submission,
    mention,
    message_conversation,
    message as message_properties,
    notification,
    notification_aggregate,
    page_assets,
    page_public,
    page_related,
    project,
    schema,
    task_dates,
    task_related,
    task_scheduling,
    user_entity,
    user_groups,
    user_permissions,
    user_related,
    user_restrictions,
)
from .entity import EntityProperties


class _CommonProperties(EntityProperties):
    created: common_entity.Created
    modified: common_entity.Modified
    kind: common_entity.Kind
    requires: common_entity.Requires
    hash: common_entity.Hash
    active: common_entity.Active


class StandardProperties(_CommonProperties):
    name: common_entity.Name


class AIReportProperties(StandardProperties):
    parent: activity.AttachedParent
    user: activity.AttachedUser
    format_version: ai_report_input.FormatVersion
    file_usage: ai_report_input.FileUsage
    instructions: activity.Instructions
    input_files: activity.InputFiles
    upload_manifest: ai_report_input.UploadManifest
    agent_manifest: ai_report_input.AgentManifest
    origin: ai_report_input.Origin
    inbound_manifest: ai_report_input.InboundManifest
    process: ai_report_process.ReportProcess
    status: ai_report_process.Status
    deferred_job: ai_report_process.DeferredJob
    summary: ai_report_process.Summary
    proposal: ai_report_proposal.Proposal
    result: ai_report_result.Result
    error: ai_report_process.Error
    pending: ai_report_process.Pending
    note: ai_report_process.Note


class CategoryProperties(StandardProperties):
    form: common_related.AttachedForm
    forms: common_related.RelatedForms
    description: common_entity.Description
    filters: category.CategoryFilters
    ai_generated: common_entity.AiGenerated


class DeferredJobProperties(StandardProperties):
    actor: deferred_job_request.Actor
    notification: deferred_job_request.Notification
    job_type: deferred_job_request.JobType
    status: deferred_job_lifecycle.Status
    job_version: deferred_job_request.Version
    idempotency_key: deferred_job_request.IdempotencyKey
    request_fingerprint: deferred_job_request.RequestFingerprint
    dispatch_state: deferred_job_dispatch.DispatchState
    task_identity: deferred_job_dispatch.TaskIdentity
    dispatched_at: deferred_job_dispatch.DispatchedAt
    deadline_at: deferred_job_dispatch.DeadlineAt
    status_revision: deferred_job_lifecycle.StatusRevision
    start_completed: deferred_job_request.StartCompleted
    telemetry_id: deferred_job_request.TelemetryId
    authorization: deferred_job_request.Authorization
    inputs: deferred_job_request.Inputs
    parameters: deferred_job_request.Parameters
    client: deferred_job_request.Client
    attempt: deferred_job_dispatch.Attempt
    lease_token: deferred_job_dispatch.LeaseToken
    lease_expires: deferred_job_dispatch.LeaseExpires
    next_attempt_at: deferred_job_dispatch.NextAttemptAt
    progress: deferred_job_lifecycle.Progress
    checkpoint: deferred_job_lifecycle.Checkpoint
    result: deferred_job_lifecycle.Result
    error: deferred_job_lifecycle.Error
    delivery: deferred_job_lifecycle.Delivery


class DeferredJobLockProperties(StandardProperties):
    target: deferred_job_lock.Target
    operation: deferred_job_lock.Operation
    idempotency_key: deferred_job_lock.IdempotencyKey
    scope: deferred_job_lock.Scope


class FileProperties(_CommonProperties):
    name: file_entity.DisplayName
    filename: file_entity.Filename
    mimetype: file_entity.Mimetype
    encoding: file_entity.Encoding
    file: file_assets.FileAsset
    size: file_entity.Size
    large: file_entity.Large
    text: file_assets.TextAsset
    html: file_entity.AsHTML
    preview: file_entity.Preview
    summary: file_entity.Summary
    page: file_related.AttachedPage
    task: file_related.AttachedTask
    task_page: file_related.TaskPage
    restricted_to: common_entity.RestrictedTo
    report_user: file_related.ReportUser
    extract: file_options.Extract
    summarize: file_options.Summarize
    options: file_options.Options


class FilterProperties(StandardProperties):
    related: filter.ConditionEntities
    parent: filter.FilterParent
    creator: filter.Creator
    table: filter.FilterTable


class FormProperties(StandardProperties):
    categories: common_related.Categories
    projects: common_related.Projects
    form_type: form.FormType
    schema: schema.Schema
    schema_format: schema.SchemaFormat
    filters: form.FormFilters
    restricted_to: common_entity.RestrictedTo
    groups: common_related.Groups
    version: form.SchemaVersion
    generation: form.FormGeneration


class UserGroupProperties(StandardProperties):
    permissions: user_groups.GroupPermissions | user_groups.PublicPermissions


class TaskHistoryProperties(EntityProperties):
    name: common_entity.Name
    created: common_entity.Created
    description: common_entity.Description
    submission: form_submission.FormSubmission
    completed_on: task_dates.CompletedOn
    completed_by: task_related.CompletedBy
    linked_pages: task_related.LinkedPages
    form: common_related.AttachedForm
    kind: common_entity.Kind
    requires: common_entity.Requires
    task: common_related.AttachedTask
    page: common_related.AttachedPage
    files: task_related.TaskFiles


class FormHistoryProperties(EntityProperties):
    created: common_entity.Created
    name: common_entity.Name
    form: common_related.AttachedForm
    kind: common_entity.Kind
    schema: schema.Schema
    schema_format: schema.SchemaFormat


class DocumentHistoryProperties(EntityProperties):
    created: common_entity.Created
    kind: common_entity.Kind
    name: common_entity.Name


class IngressProperties(_CommonProperties):
    mimetype: file_entity.Mimetype
    name: file_entity.DisplayName
    encoding: file_entity.Encoding
    file: file_assets.FileAsset
    text: file_assets.TextAsset
    rows: file_assets.Rows
    results: file_assets.Results
    filename: file_entity.Filename
    category: common_related.AttachedCategory
    project: common_related.AttachedProject
    model: common_related.AttachedModelTask
    form: common_related.AttachedForm
    stage: file_ingress.Stage
    process_csv: file_ingress.ProcessCSV
    choose_type: file_ingress.ChooseType
    choose_form: file_ingress.ChooseForm
    choose_parent: file_ingress.ChooseParent
    assign_columns: file_ingress.AssignColumns
    verify_import: file_ingress.VerifyImport
    importing: file_ingress.Importing
    completed: file_ingress.Completed


class MentionMarkerProperties(StandardProperties):
    document: mention.Document
    actor: mention.Actor
    recipient: mention.Recipient
    occurrence_id: mention.OccurrenceID
    display_name: mention.DisplayName


class MessageConversationProperties(StandardProperties):
    participants: message_conversation.Participants
    visible_to: message_conversation.VisibleTo
    participant_names: message_conversation.ParticipantNames
    last_activity: message_conversation.LastActivity
    last_sender: message_conversation.LastSender
    sequence: message_conversation.Sequence
    revision: message_conversation.Revision
    unread_counts: message_conversation.UnreadCounts
    read_through: message_conversation.ReadThrough
    cleared_through: message_conversation.ClearedThrough


class MessageProperties(StandardProperties):
    conversation: message_properties.Conversation
    sequence: message_properties.Sequence
    sender: message_properties.Sender
    recipient: message_properties.Recipient
    sender_name: message_properties.SenderName
    recipient_name: message_properties.RecipientName
    body: message_properties.Body
    hidden_for: message_properties.HiddenFor
    operation_id: message_properties.OperationID


class ModelTaskProperties(StandardProperties):
    form: project.ModelTaskForm
    project: project.ModelTaskProject


class NoteProperties(StandardProperties):
    parent: activity.AttachedParent
    user: activity.AttachedUser
    body: activity.Body
    photo: activity.Photo
    visibility: activity.Visibility
    scope: activity.Scope


class NotificationProperties(StandardProperties):
    parent: activity.AttachedParent
    target: notification.Target
    body: activity.Body
    pending: notification.Pending
    notification_type: notification.NotificationType
    event_type: notification.EventType
    sender_name: notification.SenderName
    ordinary_count: notification_aggregate.OrdinaryCount
    unread_message_count: notification_aggregate.UnreadMessageCount
    aggregate_revision: notification_aggregate.AggregateRevision
    message_revision: notification_aggregate.MessageRevision
    aggregate_generation: notification_aggregate.AggregateGeneration


class PageProperties(StandardProperties):
    form: common_related.AttachedForm
    description: common_entity.Description
    model: page_related.PageModelCategory
    categories: page_related.PageCategories
    groups: common_related.Groups
    user: page_related.PageUser
    files: page_related.PageFiles
    document: common_assets.Document
    image: page_assets.Image
    is_public: page_public.PageIsPublic
    public_id: common_entity.PublicID
    public_settings: page_public.PublicSettings
    submission: form_submission.FormSubmission
    deferred_job: common_entity.DeferredJobReference
    restricted_to: common_entity.RestrictedTo


class ProjectProperties(StandardProperties):
    model_tasks: project.ModelTasks
    description: common_entity.Description
    document: common_assets.Document
    filters: project.ProjectFilters
    is_public: common_entity.IsPublic
    public_id: common_entity.PublicID
    ai_generated: common_entity.AiGenerated


class TaskProperties(StandardProperties):
    description: common_entity.Description
    page: task_related.TaskPage
    categories: task_related.TaskCategories
    form: common_related.AttachedForm
    restricted_to: common_entity.RestrictedTo
    groups: common_related.Groups
    model: task_related.TaskModel
    project: common_related.AttachedProject
    due_date: task_dates.DueDate
    assigned_to: task_related.AssignedTo
    assigned_by: task_related.AssignedBy
    completed: task_dates.Completed
    status: task_related.TaskStatus
    completed_on: task_dates.CompletedOn
    completed_by: task_related.CompletedBy
    linked_pages: task_related.LinkedPages
    files: task_related.TaskFiles
    has_signature: task_related.HasSignature
    has_status: task_related.HasStatus
    schedule: task_scheduling.Schedule
    recurring: task_scheduling.Recurring
    scheduled: task_scheduling.Scheduled
    periodic: task_scheduling.Periodic
    submission: form_submission.FormSubmission
    deferred_job: common_entity.DeferredJobReference


class UserProperties(StandardProperties):
    page: user_related.UserPage
    email: user_entity.Email
    last_login: user_entity.LastLogin
    groups: user_related.Groups
    permissions: user_permissions.UserPermissions
    photo: user_entity.ProfilePhoto
    starred: user_related.Starred
    invalidate_cache: user_entity.InvalidateCache
    ai_access: user_entity.AIAccess
    restrictions: user_restrictions.Restrictions
    is_public: common_entity.IsPublic
    is_owner: user_entity.IsOwner
    is_admin: user_entity.IsAdmin
    allow_messages_and_mentions: user_entity.AllowMessagesAndMentions
    allow_task_assignments: user_entity.AllowTaskAssignments
    allow_site_email: user_entity.AllowSiteEmail
    allow_auto_execute: user_entity.AllowAutoExecute
    notification_email_mode: user_entity.NotificationEmailPreference
