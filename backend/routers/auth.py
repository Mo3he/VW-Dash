from __future__ import annotations
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from models import User
from config import settings

from passlib.context import CryptContext
from jose import jwt

router = APIRouter(prefix="/api/auth", tags=["auth"])

_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
_ALGORITHM = "HS256"
_TOKEN_HOURS = 24


def _hash(password: str) -> str:
    return _pwd.hash(password)


def _verify(plain: str, hashed: str) -> bool:
    return _pwd.verify(plain, hashed)


def _make_token(username: str, is_admin: bool) -> str:
    exp = datetime.now(timezone.utc) + timedelta(hours=_TOKEN_HOURS)
    return jwt.encode({"sub": username, "is_admin": is_admin, "exp": exp}, settings.jwt_secret, algorithm=_ALGORITHM)


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    payload = getattr(request.state, "jwt_payload", None)
    if not payload:
        raise HTTPException(status_code=401, detail="Not authenticated")
    user = db.query(User).filter(User.username == payload.get("sub")).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


class LoginRequest(BaseModel):
    username: str
    password: str


class CreateUserRequest(BaseModel):
    username: str
    password: str
    is_admin: bool = False


class ChangePasswordRequest(BaseModel):
    password: str


@router.get("/setup")
def setup_status(db: Session = Depends(get_db)):
    return {"needs_setup": db.query(User).count() == 0}


@router.post("/setup")
def setup(body: CreateUserRequest, db: Session = Depends(get_db)):
    if db.query(User).count() > 0:
        raise HTTPException(status_code=403, detail="Setup already complete")
    user = User(username=body.username, hashed_password=_hash(body.password), is_admin=True)
    db.add(user)
    db.commit()
    db.refresh(user)
    return {"access_token": _make_token(user.username, True), "token_type": "bearer", "username": user.username, "is_admin": True}


@router.post("/login")
def login(body: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == body.username).first()
    if not user or not _verify(body.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return {"access_token": _make_token(user.username, user.is_admin), "token_type": "bearer", "username": user.username, "is_admin": user.is_admin}


@router.get("/me")
def me(current_user: User = Depends(get_current_user)):
    return {"id": current_user.id, "username": current_user.username, "is_admin": current_user.is_admin}


@router.get("/users")
def list_users(_admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    users = db.query(User).order_by(User.created_at).all()
    return [{"id": u.id, "username": u.username, "is_admin": u.is_admin, "created_at": u.created_at} for u in users]


@router.post("/users")
def create_user(body: CreateUserRequest, _admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    if db.query(User).filter(User.username == body.username).first():
        raise HTTPException(status_code=409, detail="Username already exists")
    user = User(username=body.username, hashed_password=_hash(body.password), is_admin=body.is_admin)
    db.add(user)
    db.commit()
    db.refresh(user)
    return {"id": user.id, "username": user.username, "is_admin": user.is_admin, "created_at": user.created_at}


@router.delete("/users/{user_id}", status_code=204)
def delete_user(user_id: int, current_user: User = Depends(require_admin), db: Session = Depends(get_db)):
    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    if target.id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot delete yourself")
    if target.is_admin and db.query(User).filter(User.is_admin == True).count() <= 1:
        raise HTTPException(status_code=400, detail="Cannot delete the last admin")
    db.delete(target)
    db.commit()


@router.post("/users/{user_id}/password")
def change_password(user_id: int, body: ChangePasswordRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    if not current_user.is_admin and target.id != current_user.id:
        raise HTTPException(status_code=403, detail="Cannot change another user's password")
    target.hashed_password = _hash(body.password)
    db.commit()
    return {"ok": True}
