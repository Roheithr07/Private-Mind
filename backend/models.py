from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Boolean
from sqlalchemy.orm import relationship

try:
    from .database import Base
except ImportError:
    from database import Base


class User(Base):
    """User account model for authentication, authorization, and privacy preferences."""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    username = Column(String(100), unique=True, index=True, nullable=False)
    email = Column(String(255), unique=True, index=True, nullable=True)
    password_hash = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    memory_enabled = Column(Boolean, default=True, nullable=False)
    auto_extraction = Column(Boolean, default=True, nullable=False)
    review_before_save = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def __repr__(self) -> str:
        return f"<User(username='{self.username}', active={self.is_active})>"


class UserSession(Base):
    """Stores active user session tokens with explicit expiration and revocation."""
    __tablename__ = "user_sessions"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    token = Column(String(128), unique=True, index=True, nullable=False)
    user_id = Column(String(100), index=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    last_active_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self) -> str:
        return f"<UserSession(user='{self.user_id}', expires='{self.expires_at}')>"


class Memory(Base):
    """SQLAlchemy model representing a stored persistent memory."""
    __tablename__ = "memories"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    user_id = Column(String(100), default="default_user", index=True, nullable=False)
    title = Column(String(255), index=True, nullable=False)
    content = Column(Text, nullable=False)
    category = Column(String(100), index=True, nullable=False, default="General")
    source = Column(String(255), nullable=True, default="manual")
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationship to vector embeddings
    embedding = relationship("MemoryEmbedding", back_populates="memory", uselist=False, cascade="all, delete-orphan")
    project_links = relationship("ProjectMemory", back_populates="memory", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Memory(id={self.id}, title='{self.title}', category='{self.category}')>"


class MemoryEmbedding(Base):
    """Stores persisted vector embeddings alongside memory records."""
    __tablename__ = "memory_embeddings"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    memory_id = Column(Integer, ForeignKey("memories.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    user_id = Column(String(100), default="default_user", index=True, nullable=False)
    embedding_json = Column(Text, nullable=False)  # JSON-serialized list of floats
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    memory = relationship("Memory", back_populates="embedding")

    def __repr__(self) -> str:
        return f"<MemoryEmbedding(memory_id={self.memory_id}, user_id='{self.user_id}')>"


class ConversationMessage(Base):
    """Stores conversation turns separately from long-term factual memories."""
    __tablename__ = "conversation_messages"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    conversation_id = Column(String(100), index=True, nullable=False)
    user_id = Column(String(100), default="default_user", index=True, nullable=False)
    role = Column(String(20), nullable=False)  # 'user' or 'assistant'
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self) -> str:
        return f"<ConversationMessage(id={self.id}, conv='{self.conversation_id}', role='{self.role}')>"


class Project(Base):
    """Stores user projects with rich workspace metadata, status, priority, and progress."""
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    user_id = Column(String(100), default="default_user", index=True, nullable=False)
    title = Column(String(255), index=True, nullable=False)
    description = Column(Text, nullable=True, default="")
    status = Column(String(50), default="active", nullable=False)  # active, planning, completed, on_hold
    priority = Column(String(50), default="medium", nullable=False)  # low, medium, high, urgent
    deadline = Column(String(100), nullable=True)
    progress = Column(Integer, default=0, nullable=False)  # 0 to 100
    tags = Column(Text, nullable=True, default="[]")  # JSON string
    theme = Column(String(50), default="blue", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    notes = relationship("ProjectNote", back_populates="project", cascade="all, delete-orphan", order_by="desc(ProjectNote.created_at)")
    tasks = relationship("ProjectTask", back_populates="project", cascade="all, delete-orphan", order_by="desc(ProjectTask.created_at)")
    memory_links = relationship("ProjectMemory", back_populates="project", cascade="all, delete-orphan")
    activities = relationship("ProjectActivity", back_populates="project", cascade="all, delete-orphan", order_by="desc(ProjectActivity.created_at)")

    def __repr__(self) -> str:
        return f"<Project(id={self.id}, title='{self.title}', status='{self.status}')>"


class ProjectNote(Base):
    """Stores structured notes inside a project workspace."""
    __tablename__ = "project_notes"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(String(100), default="default_user", index=True, nullable=False)
    title = Column(String(255), nullable=False)
    content = Column(Text, nullable=False)
    is_memory = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    project = relationship("Project", back_populates="notes")

    def __repr__(self) -> str:
        return f"<ProjectNote(id={self.id}, title='{self.title}', project_id={self.project_id})>"


class ProjectTask(Base):
    """Stores trackable tasks with status, priority, and due dates."""
    __tablename__ = "project_tasks"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(String(100), default="default_user", index=True, nullable=False)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True, default="")
    status = Column(String(50), default="todo", nullable=False)  # todo, in_progress, completed
    priority = Column(String(50), default="medium", nullable=False)  # low, medium, high, urgent
    due_date = Column(String(100), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    project = relationship("Project", back_populates="tasks")

    def __repr__(self) -> str:
        return f"<ProjectTask(id={self.id}, title='{self.title}', status='{self.status}')>"


class ProjectMemory(Base):
    """Stores explicit many-to-many associations between projects and memories."""
    __tablename__ = "project_memories"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    memory_id = Column(Integer, ForeignKey("memories.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(String(100), default="default_user", index=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    project = relationship("Project", back_populates="memory_links")
    memory = relationship("Memory", back_populates="project_links")

    def __repr__(self) -> str:
        return f"<ProjectMemory(project_id={self.project_id}, memory_id={self.memory_id})>"


class ProjectActivity(Base):
    """Records audit trail of activities and updates within a project."""
    __tablename__ = "project_activities"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(String(100), default="default_user", index=True, nullable=False)
    action_type = Column(String(100), nullable=False)  # created_project, added_note, completed_task, linked_memory, etc.
    description = Column(String(500), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    project = relationship("Project", back_populates="activities")

    def __repr__(self) -> str:
        return f"<ProjectActivity(project_id={self.project_id}, action='{self.action_type}')>"

