import base64
import hashlib
import hmac
import os
import secrets
import time
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from mangum import Mangum
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from models import (
    EventType,
    Friendship,
    Match,
    MatchEvent,
    MatchStatus,
    SportType,
    Team,
    TeamMember,
    User,
    get_db,
    init_db,
)

SECRET_KEY = os.getenv("SECRET_KEY", "dev-sidestack-change-me")
TOKEN_TTL = 14 * 24 * 3600
JOIN_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"

app = FastAPI(title="SideStack", version="1.0.0")
api = APIRouter()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup():
    init_db()


# Serverless (Mangum lifespan="off") does not always run startup events.
init_db()


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 120_000).hex()
    return f"{salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt, digest = stored.split("$", 1)
    except ValueError:
        return False
    check = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 120_000).hex()
    return hmac.compare_digest(check, digest)


def make_token(user_id: int) -> str:
    payload = f"{user_id}:{int(time.time()) + TOKEN_TTL}"
    sig = hmac.new(SECRET_KEY.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(f"{payload}:{sig}".encode()).decode()


def parse_token(token: str) -> int:
    try:
        raw = base64.urlsafe_b64decode(token.encode()).decode()
        user_id_s, exp_s, sig = raw.split(":", 2)
        payload = f"{user_id_s}:{exp_s}"
        expected = hmac.new(SECRET_KEY.encode(), payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, sig):
            raise ValueError("bad sig")
        if int(time.time()) > int(exp_s):
            raise ValueError("expired")
        return int(user_id_s)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")


def current_user(
    authorization: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing token")
    user_id = parse_token(authorization.split(" ", 1)[1].strip())
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


def optional_user(
    authorization: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
) -> Optional[User]:
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    try:
        return current_user(authorization, db)
    except HTTPException:
        return None


class RegisterIn(BaseModel):
    username: str = Field(min_length=3, max_length=32)
    password: str = Field(min_length=6, max_length=128)
    primary_sport: str


class LoginIn(BaseModel):
    username: str
    password: str


class TeamCreateIn(BaseModel):
    name: str = Field(min_length=2, max_length=64)
    sport_type: str


class JoinTeamIn(BaseModel):
    join_code: str = Field(min_length=4, max_length=4)


class FriendIn(BaseModel):
    username: str


class ChallengeIn(BaseModel):
    team_id: int
    opponent_team_id: int
    referee_id: int


class EventIn(BaseModel):
    player_id: int
    event_type: str


def sport_from_str(value: str) -> SportType:
    normalized = (value or "").strip().lower()
    if normalized == "cricket":
        raise HTTPException(
            status_code=400,
            detail="Cricket matches take 5 days, we don't have server space for that. Pick a real sport!",
        )
    try:
        return SportType(normalized)
    except ValueError:
        raise HTTPException(status_code=400, detail="Sport must be basketball or football")


def event_from_str(value: str) -> EventType:
    try:
        return EventType(value)
    except ValueError:
        raise HTTPException(status_code=400, detail="Unknown event type")


def are_friends(db: Session, a: int, b: int) -> bool:
    if a == b:
        return True
    row = (
        db.query(Friendship)
        .filter(
            ((Friendship.user_id == a) & (Friendship.friend_id == b))
            | ((Friendship.user_id == b) & (Friendship.friend_id == a))
        )
        .first()
    )
    return row is not None


def team_member_ids(db: Session, team_id: int) -> List[int]:
    return [m.user_id for m in db.query(TeamMember).filter(TeamMember.team_id == team_id).all()]


def user_on_team(db: Session, user_id: int, team_id: int) -> bool:
    return (
        db.query(TeamMember)
        .filter(TeamMember.team_id == team_id, TeamMember.user_id == user_id)
        .first()
        is not None
    )


def unique_join_code(db: Session) -> str:
    for _ in range(40):
        code = "".join(secrets.choice(JOIN_ALPHABET) for _ in range(4))
        if not db.query(Team).filter(Team.join_code == code).first():
            return code
    raise HTTPException(status_code=500, detail="Could not generate join code")


def user_public(user: User) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "primary_sport": user.primary_sport.value,
    }


def team_public(team: Team, db: Session) -> dict:
    members = (
        db.query(User)
        .join(TeamMember, TeamMember.user_id == User.id)
        .filter(TeamMember.team_id == team.id)
        .all()
    )
    return {
        "id": team.id,
        "name": team.name,
        "join_code": team.join_code,
        "captain_id": team.captain_id,
        "sport_type": team.sport_type.value,
        "members": [user_public(u) for u in members],
    }


def scoring_value(event_type: EventType) -> int:
    return {
        EventType.pt1: 1,
        EventType.pt2: 2,
        EventType.pt3: 3,
        EventType.goal: 1,
    }.get(event_type, 0)


def player_points(events: List[MatchEvent], player_id: int) -> int:
    return sum(scoring_value(e.event_type) for e in events if e.player_id == player_id)


def lifetime_stats(db: Session, user_id: int) -> dict:
    events = (
        db.query(MatchEvent)
        .join(Match, Match.id == MatchEvent.match_id)
        .filter(MatchEvent.player_id == user_id, Match.status == MatchStatus.completed)
        .all()
    )
    stats = {
        "points": 0,
        "goals": 0,
        "ft": 0,
        "twos": 0,
        "threes": 0,
        "fouls": 0,
        "yellow_cards": 0,
        "red_cards": 0,
        "games": 0,
        "mvp_count": 0,
    }
    for e in events:
        if e.event_type == EventType.pt1:
            stats["ft"] += 1
            stats["points"] += 1
        elif e.event_type == EventType.pt2:
            stats["twos"] += 1
            stats["points"] += 2
        elif e.event_type == EventType.pt3:
            stats["threes"] += 1
            stats["points"] += 3
        elif e.event_type == EventType.goal:
            stats["goals"] += 1
            stats["points"] += 1
        elif e.event_type == EventType.foul:
            stats["fouls"] += 1
        elif e.event_type == EventType.yellow_card:
            stats["yellow_cards"] += 1
        elif e.event_type == EventType.red_card:
            stats["red_cards"] += 1

    match_ids = {e.match_id for e in events}
    stats["games"] = len(match_ids)
    stats["mvp_count"] = db.query(Match).filter(Match.mvp_id == user_id).count()
    return stats


def serialize_match(match: Match, db: Session, include_events: bool = True) -> dict:
    events = (
        db.query(MatchEvent)
        .filter(MatchEvent.match_id == match.id)
        .order_by(MatchEvent.timestamp.asc())
        .all()
    )
    mvp_user = db.get(User, match.mvp_id) if match.mvp_id else None
    payload = {
        "id": match.id,
        "sport_type": match.sport_type.value,
        "status": match.status.value,
        "team1": team_public(match.team1, db),
        "team2": team_public(match.team2, db),
        "referee": user_public(match.referee),
        "team1_score": match.team1_score,
        "team2_score": match.team2_score,
        "mvp": user_public(mvp_user) if mvp_user else None,
        "created_at": match.created_at.isoformat() if match.created_at else None,
        "ended_at": match.ended_at.isoformat() if match.ended_at else None,
    }
    if include_events:
        payload["events"] = [
            {
                "id": e.id,
                "player_id": e.player_id,
                "player": user_public(e.player),
                "event_type": e.event_type.value,
                "timestamp": e.timestamp.isoformat(),
            }
            for e in events
        ]
    return payload


@api.get("/health")
def health():
    return {"ok": True, "service": "sidestack"}


@api.post("/auth/register")
def register(body: RegisterIn, db: Session = Depends(get_db)):
    username = body.username.strip()
    if not username.isalnum():
        raise HTTPException(status_code=400, detail="Username must be alphanumeric")
    sport = sport_from_str(body.primary_sport)
    if db.query(User).filter(User.username.ilike(username)).first():
        raise HTTPException(status_code=409, detail="Username already taken")
    user = User(
        username=username,
        password_hash=hash_password(body.password),
        primary_sport=sport,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return {"token": make_token(user.id), "user": user_public(user)}


@api.post("/auth/login")
def login(body: LoginIn, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username.ilike(body.username.strip())).first()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    return {"token": make_token(user.id), "user": user_public(user)}


@api.get("/me")
def me(user: User = Depends(current_user), db: Session = Depends(get_db)):
    teams = (
        db.query(Team)
        .join(TeamMember, TeamMember.team_id == Team.id)
        .filter(TeamMember.user_id == user.id)
        .all()
    )
    recent = (
        db.query(Match)
        .filter(
            (Match.team1_id.in_([t.id for t in teams] or [-1]))
            | (Match.team2_id.in_([t.id for t in teams] or [-1]))
            | (Match.referee_id == user.id)
        )
        .order_by(Match.created_at.desc())
        .limit(12)
        .all()
    )
    return {
        "user": user_public(user),
        "stats": lifetime_stats(db, user.id),
        "teams": [team_public(t, db) for t in teams],
        "recent_matches": [serialize_match(m, db, include_events=False) for m in recent],
    }


@api.get("/users/search")
def search_users(q: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    query = q.strip()
    if len(query) < 1:
        return {"users": []}
    rows = (
        db.query(User)
        .filter(User.username.ilike(f"%{query}%"), User.id != user.id)
        .limit(20)
        .all()
    )
    out = []
    for u in rows:
        out.append({**user_public(u), "is_friend": are_friends(db, user.id, u.id)})
    return {"users": out}


@api.get("/friends")
def list_friends(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.query(Friendship).filter(Friendship.user_id == user.id).all()
    friends = []
    for row in rows:
        f = db.get(User, row.friend_id)
        if f:
            friends.append({**user_public(f), "stats_teaser": lifetime_stats(db, f.id)["games"]})
    return {"friends": friends}


@api.post("/friends")
def add_friend(body: FriendIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    other = db.query(User).filter(User.username.ilike(body.username.strip())).first()
    if not other:
        raise HTTPException(status_code=404, detail="User not found")
    if other.id == user.id:
        raise HTTPException(status_code=400, detail="You cannot add yourself")
    if are_friends(db, user.id, other.id):
        return {"ok": True, "friend": user_public(other)}
    db.add(Friendship(user_id=user.id, friend_id=other.id))
    db.add(Friendship(user_id=other.id, friend_id=user.id))
    db.commit()
    return {"ok": True, "friend": user_public(other)}


@api.get("/users/{user_id}")
def user_profile(user_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    target = db.get(User, user_id)
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    basic = user_public(target)
    if not are_friends(db, user.id, target.id):
        return {**basic, "friends_only": True, "detail": "Add this player as a friend to view full stats."}
    teams = (
        db.query(Team)
        .join(TeamMember, TeamMember.team_id == Team.id)
        .filter(TeamMember.user_id == target.id)
        .all()
    )
    return {
        **basic,
        "friends_only": False,
        "stats": lifetime_stats(db, target.id),
        "teams": [team_public(t, db) for t in teams],
    }


@api.post("/teams")
def create_team(body: TeamCreateIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    sport = sport_from_str(body.sport_type)
    team = Team(
        name=body.name.strip(),
        join_code=unique_join_code(db),
        captain_id=user.id,
        sport_type=sport,
    )
    db.add(team)
    db.flush()
    db.add(TeamMember(team_id=team.id, user_id=user.id))
    db.commit()
    db.refresh(team)
    return team_public(team, db)


@api.post("/teams/join")
def join_team(body: JoinTeamIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    code = body.join_code.strip().upper()
    team = db.query(Team).filter(Team.join_code == code).first()
    if not team:
        raise HTTPException(status_code=404, detail="Invalid join code")
    if user_on_team(db, user.id, team.id):
        return team_public(team, db)
    db.add(TeamMember(team_id=team.id, user_id=user.id))
    db.commit()
    return team_public(team, db)


@api.get("/teams")
def my_teams(user: User = Depends(current_user), db: Session = Depends(get_db)):
    teams = (
        db.query(Team)
        .join(TeamMember, TeamMember.team_id == Team.id)
        .filter(TeamMember.user_id == user.id)
        .all()
    )
    return {"teams": [team_public(t, db) for t in teams]}


@api.get("/teams/opponents")
def opponents(sport_type: str, team_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    sport = sport_from_str(sport_type)
    rows = db.query(Team).filter(Team.sport_type == sport, Team.id != team_id).all()
    return {"teams": [team_public(t, db) for t in rows]}


@api.get("/teams/{team_id}/referees")
def eligible_referees(team_id: int, opponent_team_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    team = db.get(Team, team_id)
    opp = db.get(Team, opponent_team_id)
    if not team or not opp:
        raise HTTPException(status_code=404, detail="Team not found")
    if team.captain_id != user.id:
        raise HTTPException(status_code=403, detail="Only the captain can nominate a referee")
    blocked = set(team_member_ids(db, team.id)) | set(team_member_ids(db, opp.id))
    friend_rows = db.query(Friendship).filter(Friendship.user_id == user.id).all()
    refs = []
    for row in friend_rows:
        if row.friend_id in blocked:
            continue
        f = db.get(User, row.friend_id)
        if f:
            refs.append(user_public(f))
    return {"referees": refs}


@api.post("/matches/challenge")
def challenge(body: ChallengeIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    team = db.get(Team, body.team_id)
    opp = db.get(Team, body.opponent_team_id)
    ref = db.get(User, body.referee_id)
    if not team or not opp or not ref:
        raise HTTPException(status_code=404, detail="Team or referee not found")
    if team.captain_id != user.id:
        raise HTTPException(status_code=403, detail="Only the team captain can issue a challenge")
    if team.id == opp.id:
        raise HTTPException(status_code=400, detail="You cannot challenge your own team")
    if team.sport_type != opp.sport_type:
        raise HTTPException(status_code=400, detail="Both teams must play the same sport")
    if not are_friends(db, user.id, ref.id):
        raise HTTPException(status_code=400, detail="Referee must be a third-party friend")
    if user_on_team(db, ref.id, team.id) or user_on_team(db, ref.id, opp.id):
        raise HTTPException(status_code=400, detail="Referee cannot be on either roster")
    match = Match(
        team1_id=team.id,
        team2_id=opp.id,
        referee_id=ref.id,
        sport_type=team.sport_type,
        status=MatchStatus.pending,
        team1_score=0,
        team2_score=0,
    )
    db.add(match)
    db.commit()
    db.refresh(match)
    return serialize_match(match, db)


@api.get("/matches")
def list_matches(user: User = Depends(current_user), db: Session = Depends(get_db)):
    team_ids = [m.team_id for m in db.query(TeamMember).filter(TeamMember.user_id == user.id).all()]
    rows = (
        db.query(Match)
        .filter(
            (Match.team1_id.in_(team_ids or [-1]))
            | (Match.team2_id.in_(team_ids or [-1]))
            | (Match.referee_id == user.id)
        )
        .order_by(Match.created_at.desc())
        .limit(40)
        .all()
    )
    return {"matches": [serialize_match(m, db, include_events=False) for m in rows]}


@api.get("/matches/{match_id}")
def get_match(match_id: int, db: Session = Depends(get_db)):
    match = db.get(Match, match_id)
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    return serialize_match(match, db)


@api.post("/matches/{match_id}/start")
def start_match(match_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    match = db.get(Match, match_id)
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    if match.referee_id != user.id:
        raise HTTPException(status_code=403, detail="Only the nominated referee can start the match")
    if match.status != MatchStatus.pending:
        raise HTTPException(status_code=400, detail="Match is not pending")
    match.status = MatchStatus.active
    db.commit()
    db.refresh(match)
    return serialize_match(match, db)


@api.post("/matches/{match_id}/events")
def add_event(match_id: int, body: EventIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    match = db.get(Match, match_id)
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    if match.referee_id != user.id:
        raise HTTPException(status_code=403, detail="Only the referee can log events")
    if match.status != MatchStatus.active:
        raise HTTPException(status_code=400, detail="Match is not live")
    event_type = event_from_str(body.event_type)
    allowed = {
        SportType.basketball: {EventType.pt1, EventType.pt2, EventType.pt3, EventType.foul},
        SportType.football: {EventType.goal, EventType.yellow_card, EventType.red_card, EventType.foul},
    }
    if event_type not in allowed[match.sport_type]:
        raise HTTPException(status_code=400, detail="Event is not valid for this sport")
    roster = set(team_member_ids(db, match.team1_id)) | set(team_member_ids(db, match.team2_id))
    if body.player_id not in roster:
        raise HTTPException(status_code=400, detail="Player is not on either roster")
    event = MatchEvent(match_id=match.id, player_id=body.player_id, event_type=event_type)
    db.add(event)
    points = scoring_value(event_type)
    if points:
        if user_on_team(db, body.player_id, match.team1_id):
            match.team1_score += points
        else:
            match.team2_score += points
    db.commit()
    db.refresh(match)
    return serialize_match(match, db)


@api.post("/matches/{match_id}/end")
def end_match(match_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    match = db.get(Match, match_id)
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    if match.referee_id != user.id:
        raise HTTPException(status_code=403, detail="Only the referee can confirm stats")
    if match.status != MatchStatus.active:
        raise HTTPException(status_code=400, detail="Match is not live")
    events = db.query(MatchEvent).filter(MatchEvent.match_id == match.id).all()
    roster = set(team_member_ids(db, match.team1_id)) | set(team_member_ids(db, match.team2_id))
    best_id = None
    best_pts = -1
    for pid in roster:
        pts = player_points(events, pid)
        if pts > best_pts:
            best_pts = pts
            best_id = pid
    match.mvp_id = best_id if best_pts > 0 else None
    match.status = MatchStatus.completed
    match.ended_at = datetime.utcnow()
    db.commit()
    db.refresh(match)
    return serialize_match(match, db)


app.include_router(api)
app.include_router(api, prefix="/api")

# Local convenience: serve the static frontend when not running as a Netlify function.
if not os.getenv("NETLIFY") and not os.getenv("AWS_LAMBDA_FUNCTION_NAME"):
    public_dir = os.path.join(os.path.dirname(__file__), "public")
    if os.path.isdir(public_dir):
        @app.get("/")
        def index_page():
            return FileResponse(os.path.join(public_dir, "index.html"))

        css_dir = os.path.join(public_dir, "css")
        js_dir = os.path.join(public_dir, "js")
        if os.path.isdir(css_dir):
            app.mount("/css", StaticFiles(directory=css_dir), name="css")
        if os.path.isdir(js_dir):
            app.mount("/js", StaticFiles(directory=js_dir), name="js")


handler = Mangum(app, lifespan="off")
