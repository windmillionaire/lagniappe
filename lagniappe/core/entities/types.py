from enum import Enum

from .category import Category, UserCategory
from .ai_report import AIReport
from .condition import Condition
from .deferred_job import DeferredJob
from .deferred_job_lock import DeferredJobLock
from .file import File
from .filter import Filter
from .form import Form
from .group import PublicGroup, UserGroup
from .history import TaskHistory, FormHistory, DocumentHistory
from .home import Home
from .ingress import Ingress
from .model_task import ModelTask
from .message import Message, MessageConversation
from .mention import MentionMarker
from .notification import Notification
from .note import Note
from .page import Page
from .project import Project
from .task import Task
from .user import User


class EntityType(Enum):
    DEFERRED_JOB = DeferredJob
    JOB = DEFERRED_JOB
    DEFERRED_JOB_LOCK = DeferredJobLock
    JOB_LOCK = DEFERRED_JOB_LOCK
    USER = User
    PROJECT = Project
    MODEL_TASK = ModelTask
    MODEL = MODEL_TASK
    FILE = File
    INGRESS = Ingress
    FORM = Form
    CATEGORY = Category
    USERS = UserCategory
    PAGE = Page
    TASK = Task
    USER_GROUP = UserGroup
    GROUP = USER_GROUP
    PUBLIC_GROUP = PublicGroup
    HOME = Home
    FILTER = Filter
    CONDITION = Condition
    TASK_HISTORY = TaskHistory
    NOTIFICATION = Notification
    NOTE = Note
    FORM_HISTORY = FormHistory
    DOCUMENT_HISTORY = DocumentHistory
    REPORT = AIReport
    MESSAGE_CONVERSATION = MessageConversation
    MESSAGE = Message
    MENTION_MARKER = MentionMarker
