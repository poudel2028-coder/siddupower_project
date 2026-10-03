import enum
import os
from datetime import datetime

from sqlalchemy import (
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    create_engine,
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker


def normalize_database_url(url: str) -> str:
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg2://", 1)
    if url.startswith("postgresql://") and "+psycopg2" not in url:
        return url.replace("postgresql://", "postgresql+psycopg2://", 1)
    return url


def resolve_database_url() -> str:
    """
    Production (Netlify) MUST use Postgres via DATABASE_URL.
    Local SQLite is only used when not running on Netlify and no URL is set.
    """
    raw = os.getenv("DATABASE_URL", "").strip()
    on_netlify = bool(os.getenv("NETLIFY") or os.getenv("AWS_LAMBDA_FUNCTION_NAME"))
    if on_netlify:
        if not raw:
            raise RuntimeError(
                "DATABASE_URL is required on Netlify. Use Neon, Supabase, or Railway Postgres."
            )
        if raw.startswith("sqlite"):
            raise RuntimeError("SQLite is not allowed on Netlify (ephemeral filesystem).")
        return normalize_database_url(raw)
    if raw:
        return normalize_database_url(raw)
    return "sqlite:///./sidestack.db"


DATABASE_URL = resolve_database_url()
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, pool_pre_ping=True, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class SportType(str, enum.Enum):
    basketball = "basketball"
    football = "football"


class MatchStatus(str, enum.Enum):
    pending = "pending"
    active = "active"
    completed = "completed"


class EventType(str, enum.Enum):
    pt1 = "1pt"
    pt2 = "2pt"
    pt3 = "3pt"
    goal = "goal"
    yellow_card = "yellow_card"
    red_card = "red_card"
    foul = "foul"


enum_kwargs = dict(native_enum=False, values_callable=lambda obj: [e.value for e in obj])


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(32), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    primary_sport = Column(Enum(SportType, **enum_kwargs), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    captained_teams = relationship("Team", back_populates="captain")
    memberships = relationship("TeamMember", back_populates="user")


class Friendship(Base):
    __tablename__ = "friendships"
    __table_args__ = (UniqueConstraint("user_id", "friend_id", name="uq_friendship"),)

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    friend_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class Team(Base):
    __tablename__ = "teams"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(64), nullable=False)
    join_code = Column(String(4), unique=True, nullable=False, index=True)
    captain_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    sport_type = Column(Enum(SportType, **enum_kwargs), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    captain = relationship("User", back_populates="captained_teams")
    members = relationship("TeamMember", back_populates="team")


class TeamMember(Base):
    __tablename__ = "team_members"
    __table_args__ = (UniqueConstraint("team_id", "user_id", name="uq_team_member"),)

    id = Column(Integer, primary_key=True)
    team_id = Column(Integer, ForeignKey("teams.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    joined_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    team = relationship("Team", back_populates="members")
    user = relationship("User", back_populates="memberships")


class Match(Base):
    __tablename__ = "matches"

    id = Column(Integer, primary_key=True, index=True)
    team1_id = Column(Integer, ForeignKey("teams.id"), nullable=False)
    team2_id = Column(Integer, ForeignKey("teams.id"), nullable=False)
    referee_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    sport_type = Column(Enum(SportType, **enum_kwargs), nullable=False)
    status = Column(Enum(MatchStatus, **enum_kwargs), nullable=False, default=MatchStatus.pending)
    team1_score = Column(Integer, nullable=False, default=0)
    team2_score = Column(Integer, nullable=False, default=0)
    mvp_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    ended_at = Column(DateTime, nullable=True)

    team1 = relationship("Team", foreign_keys=[team1_id])
    team2 = relationship("Team", foreign_keys=[team2_id])
    referee = relationship("User", foreign_keys=[referee_id])
    mvp = relationship("User", foreign_keys=[mvp_id])
    events = relationship("MatchEvent", back_populates="match")


class MatchEvent(Base):
    __tablename__ = "match_events"

    id = Column(Integer, primary_key=True, index=True)
    match_id = Column(Integer, ForeignKey("matches.id"), nullable=False, index=True)
    player_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    event_type = Column(Enum(EventType, **enum_kwargs), nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False)

    match = relationship("Match", back_populates="events")
    player = relationship("User")


def init_db() -> None:
    Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
