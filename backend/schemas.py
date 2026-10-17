from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field


class MemoryBase(BaseModel):
    title: str = Field(..., min_length=1, max_length=255, description="Title of the memory", examples=["NVIDIA Hackathon Plan"])
    content: str = Field(..., min_length=1, description="Content or details of the memory", examples=["Building PrivateMind privacy-first assistant"])
    category: str = Field(default="General", max_length=100, description="Memory category", examples=["Projects"])
    source: Optional[str] = Field(default="manual", max_length=255, description="Source of the memory", examples=["manual"])
    user_id: Optional[str] = Field(default="default_user", max_length=100, description="Owner or user identifier", examples=["default_user"])


class MemoryCreate(MemoryBase):
    """Schema used when creating a new memory record."""
    pass


class MemoryUpdate(BaseModel):
    """Schema used when updating an existing memory (all fields optional)."""
    title: Optional[str] = Field(default=None, min_length=1, max_length=255, description="Updated title")
    content: Optional[str] = Field(default=None, min_length=1, description="Updated content")
    category: Optional[str] = Field(default=None, max_length=100, description="Updated category")
    source: Optional[str] = Field(default=None, max_length=255, description="Updated source")
    user_id: Optional[str] = Field(default=None, max_length=100, description="Updated user identifier")


class MemoryResponse(MemoryBase):
    """Schema returned by memory API endpoints."""
    id: int
    user_id: str
    title: str
    content: str
    category: str
    source: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class MemoryDeleteResponse(BaseModel):
    """Schema returned after memory deletion."""
    status: str = "deleted"
    id: int
    message: str = "Memory deleted successfully"


# -----------------------------------------------------------------------------
# Phase 3 Extraction & Management Schemas
# -----------------------------------------------------------------------------
class CandidateMemory(BaseModel):
    """Represents an extracted candidate fact before or during user review."""
    candidate_id: str = Field(..., description="Temporary unique candidate identifier")
    user_id: str = Field(default="default_user", description="User identifier")
    title: str = Field(..., min_length=1, max_length=255, description="Suggested concise title")
    content: str = Field(..., min_length=1, description="Extracted durable fact")
    category: str = Field(default="General", description="Classified category")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence score")
    is_durable: bool = Field(default=True, description="Whether this is a durable fact rather than transient filler")
    action: str = Field(default="create", description="Proposed action: create, update, duplicate, conflict")
    existing_memory_id: Optional[int] = Field(default=None, description="Referenced existing memory ID if update, duplicate, or conflict")
    explanation: str = Field(default="", description="Reasoning for classification and proposed action")
    source: str = Field(default="conversation_extraction", description="Origin of extracted fact")


class ExtractionRequest(BaseModel):
    """Request payload for extracting candidate memories from a user message."""
    message: str = Field(..., min_length=1, description="The message from which to extract memories", examples=["I'm learning Python and building a water quality monitoring project using ESP32."])
    user_id: Optional[str] = Field(default="default_user", description="User identifier")
    review_before_saving: bool = Field(default=True, description="If True, returns candidates for preview. If False, auto-saves non-duplicate facts.")


class ExtractionResponse(BaseModel):
    """Response returned by the memory extraction endpoint."""
    message: str
    candidates: List[CandidateMemory]
    auto_saved: bool
    saved_memories: List[MemoryResponse] = []
    review_required: bool


class CandidateApprovalItem(BaseModel):
    """Single candidate submitted for approval."""
    candidate_id: Optional[str] = None
    title: str = Field(..., min_length=1, max_length=255)
    content: str = Field(..., min_length=1)
    category: str = Field(default="General")
    action: Optional[str] = Field(default="create", description="Action to perform: create, update, skip")
    existing_memory_id: Optional[int] = None
    user_id: Optional[str] = Field(default="default_user")
    source: Optional[str] = Field(default="conversation_extraction")


class ApproveMemoriesRequest(BaseModel):
    """Request payload to approve and save or update candidate memories."""
    candidates: List[CandidateApprovalItem]
    user_id: Optional[str] = Field(default="default_user")


class ApproveMemoriesResponse(BaseModel):
    """Response returned after approving candidate memories."""
    status: str = "approved"
    saved_memories: List[MemoryResponse] = []
    updated_memories: List[MemoryResponse] = []
    skipped_count: int = 0
    message: str


class RejectMemoriesRequest(BaseModel):
    """Request payload to reject candidate memories."""
    candidate_ids: List[str]
    reason: Optional[str] = None


class RejectMemoriesResponse(BaseModel):
    """Response returned after rejecting candidate memories."""
    status: str = "rejected"
    rejected_count: int
    message: str


# -----------------------------------------------------------------------------
# Phase 4 Semantic Search & Retrieval Schemas
# -----------------------------------------------------------------------------
class MemorySearchRequest(BaseModel):
    """Request payload for semantic retrieval of relevant memories."""
    query: str = Field(..., min_length=1, description="User question or statement", examples=["Which hardware am I using for my water monitoring project?"])
    user_id: Optional[str] = Field(default="default_user", description="User identifier")
    threshold: float = Field(default=0.3, ge=0.0, le=1.0, description="Minimum cosine similarity score required (0.0 to 1.0)")
    limit: int = Field(default=5, ge=1, le=50, description="Maximum number of relevant memories to retrieve")
    category: Optional[str] = Field(default=None, description="Optional category filter")
    keyword: Optional[str] = Field(default=None, description="Optional keyword filter")
    search_mode: Optional[str] = Field(default="semantic", description="Search mode: 'semantic' (default) or 'keyword'")


class MemorySearchResultItem(BaseModel):
    """Individual retrieved memory with similarity score."""
    memory_id: int
    title: str
    content: str
    category: str
    score: float
    source: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class MemorySearchResponse(BaseModel):
    """Response from semantic memory retrieval."""
    query: str
    total_found: int
    threshold: float
    matches: List[MemorySearchResultItem]
    formatted_context: str
    categories: List[str]


class MemoryContextResponse(BaseModel):
    """Response returning LLM-formatted context for a single memory."""
    memory_id: int
    formatted_context: str
    memory: MemoryResponse


# -----------------------------------------------------------------------------
# Phase 5 Conversational Chat Schemas
# -----------------------------------------------------------------------------
class ChatMessageRequest(BaseModel):
    """Request payload for conversational chat with memory-augmented context."""
    message: str = Field(..., min_length=1, max_length=4000, description="User input message or question")
    conversation_id: Optional[str] = Field(default=None, description="Optional conversation session ID (auto-generated if omitted)")
    user_id: Optional[str] = Field(default="default_user", description="User identifier")
    retrieval_threshold: float = Field(default=0.25, ge=0.0, le=1.0, description="Similarity threshold for memory retrieval")
    max_memories: int = Field(default=5, ge=0, le=20, description="Maximum number of memories to include in context")


class ConversationMessageItem(BaseModel):
    """Representation of an individual conversation turn."""
    id: int
    conversation_id: str
    role: str
    content: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ChatMessageResponse(BaseModel):
    """Response returned by the memory-aware chat endpoint."""
    conversation_id: str
    message: str
    response: str
    model: str
    provider: str
    is_mock: bool
    memories_retrieved: List[MemorySearchResultItem] = []
    memory_ids_used: List[int] = []
    extracted_candidates: List[CandidateMemory] = []
    created_at: datetime
    latency_ms: Optional[float] = None
    usage: Optional[Dict[str, Any]] = None


class ConversationHistoryResponse(BaseModel):
    """Response returned when fetching chat conversation history."""
    conversation_id: str
    messages: List[ConversationMessageItem]
    total: int


# -----------------------------------------------------------------------------
# -----------------------------------------------------------------------------
# Phase 6 & Phase 10 Functional Projects & Workspace Schemas
# -----------------------------------------------------------------------------
class ProjectItem(BaseModel):
    id: int
    title: str
    description: str
    status: str = "active"
    priority: str = "medium"
    deadline: Optional[str] = None
    progress: int = 0
    tags: List[str] = []
    theme: str = "blue"
    notes_count: int = 0
    tasks_count: int = 0
    completed_tasks_count: int = 0
    memories_count: int = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class ProjectsListResponse(BaseModel):
    projects: List[ProjectItem]
    total_projects: int
    total_notes: int
    related_memories_count: int
    active_tasks_count: int = 0
    connected: bool = True


class ProjectCreate(BaseModel):
    title: str = Field(..., min_length=1, description="Project name")
    description: Optional[str] = Field(default="", description="Project description")
    status: Optional[str] = Field(default="active", description="Project status: active, planning, completed, on_hold")
    priority: Optional[str] = Field(default="medium", description="Project priority: low, medium, high, urgent")
    deadline: Optional[str] = Field(default=None, description="Optional deadline date string")
    progress: Optional[int] = Field(default=0, ge=0, le=100, description="Project progress percentage")
    user_id: Optional[str] = Field(default="default_user", description="User identifier")
    tags: Optional[List[str]] = Field(default_factory=list, description="Project tags")
    theme: Optional[str] = Field(default="blue", description="Theme color")


class ProjectUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1)
    description: Optional[str] = None
    status: Optional[str] = None
    priority: Optional[str] = None
    deadline: Optional[str] = None
    progress: Optional[int] = Field(default=None, ge=0, le=100)
    tags: Optional[List[str]] = None
    theme: Optional[str] = None


class ProjectNoteCreate(BaseModel):
    title: str = Field(..., min_length=1, description="Note title")
    content: str = Field(..., min_length=1, description="Note content")


class ProjectNoteUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1)
    content: Optional[str] = Field(default=None, min_length=1)


class ProjectNoteItem(BaseModel):
    id: int
    project_id: int
    title: str
    content: str
    is_memory: bool = False
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ProjectTaskCreate(BaseModel):
    title: str = Field(..., min_length=1, description="Task title")
    description: Optional[str] = Field(default="", description="Task description")
    status: Optional[str] = Field(default="todo", description="Task status: todo, in_progress, completed")
    priority: Optional[str] = Field(default="medium", description="Priority: low, medium, high, urgent")
    due_date: Optional[str] = Field(default=None, description="Optional due date")


class ProjectTaskUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    priority: Optional[str] = None
    due_date: Optional[str] = None


class ProjectTaskItem(BaseModel):
    id: int
    project_id: int
    title: str
    description: Optional[str] = ""
    status: str = "todo"
    priority: str = "medium"
    due_date: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ProjectMemoryAttach(BaseModel):
    memory_id: int = Field(..., description="ID of existing memory to attach to project")


class ProjectActivityItem(BaseModel):
    id: int
    project_id: int
    action_type: str
    description: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ProjectDetailResponse(BaseModel):
    project: ProjectItem
    notes: List[ProjectNoteItem] = []
    tasks: List[ProjectTaskItem] = []
    memories: List[MemoryResponse] = []
    activities: List[ProjectActivityItem] = []


class ProjectChatRequest(BaseModel):
    message: Optional[str] = Field(default=None, max_length=4000, description="Question about this project")
    query: Optional[str] = Field(default=None, max_length=4000, description="Alternative alias for question")
    conversation_id: Optional[str] = Field(default=None, description="Optional conversation session ID")
    user_id: Optional[str] = Field(default="default_user", description="User identifier")


class BulkDeleteResponse(BaseModel):
    status: str = "deleted"
    deleted_count: int
    message: str


# -----------------------------------------------------------------------------
# Phase 7 Authentication, Authorization & Privacy Schemas
# -----------------------------------------------------------------------------
class UserRegisterRequest(BaseModel):
    """Payload to register a new user account."""
    username: str = Field(..., min_length=3, max_length=50, pattern=r"^[a-zA-Z0-9_\-]+$", description="Unique username")
    password: str = Field(..., min_length=8, max_length=128, description="User password (min 8 characters)")
    email: Optional[str] = Field(default=None, max_length=255, description="Optional email address")


class UserLoginRequest(BaseModel):
    """Payload to authenticate an existing user."""
    username: str = Field(..., min_length=1, max_length=50, description="Username")
    password: str = Field(..., min_length=1, max_length=128, description="Password")


class UserResponse(BaseModel):
    """Public representation of user account and privacy preferences."""
    username: str
    email: Optional[str] = None
    is_active: bool = True
    memory_enabled: bool = True
    auto_extraction: bool = True
    review_before_save: bool = True
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AuthTokenResponse(BaseModel):
    """Response returned upon successful registration or login."""
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


class UserSettingsUpdate(BaseModel):
    """Payload to update user privacy and learning preferences."""
    memory_enabled: Optional[bool] = None
    auto_extraction: Optional[bool] = None
    review_before_save: Optional[bool] = None


class DeleteAccountResponse(BaseModel):
    """Response after deleting account and all associated data."""
    status: str = "deleted"
    message: str = "Account and all associated data deleted successfully"


class DeleteConversationResponse(BaseModel):
    """Response returned after deleting a conversation session."""
    status: str = "deleted"
    conversation_id: str
    deleted_turns_count: int
    message: str = "Conversation history deleted successfully"


class ConversationSessionItem(BaseModel):
    """Summary of an active user conversation session."""
    conversation_id: str
    turn_count: int
    last_active_at: datetime
    preview: Optional[str] = None


class DataExportResponse(BaseModel):
    """Portable JSON export of all memories and conversations owned by a user."""
    user_id: str
    exported_at: datetime
    version: str = "1.0"
    total_memories: int
    memories: List[MemoryResponse]
    total_conversations: int
    conversations: List[dict]


