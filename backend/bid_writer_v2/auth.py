from __future__ import annotations

import base64
import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

import httpx

from .audit import AuditService
from .database import Database
from .settings import Settings


ROLE_PERMISSIONS = {
    "viewer": {"read"},
    "author": {"read", "write", "generate", "search"},
    "reviewer": {"read", "write", "generate", "search", "review", "publish", "export"},
    "admin": {"*"},
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


class AuthService:
    session_cookie = "bid_writer_session"
    csrf_cookie = "bid_writer_csrf"

    def __init__(self, db: Database, settings: Settings, audit: AuditService) -> None:
        self.db = db
        self.settings = settings
        self.audit = audit
        if settings.auth_enabled:
            if len(settings.session_secret) < 24:
                raise RuntimeError("启用认证时 BID_WRITER_SESSION_SECRET 至少需要24个字符")
            self.bootstrap_admin()

    def bootstrap_admin(self) -> None:
        with self.db.connect() as conn:
            exists = conn.execute("SELECT id FROM app_users LIMIT 1").fetchone()
        if exists:
            return
        if not self.settings.bootstrap_password:
            raise RuntimeError("首次启用认证必须设置 BID_WRITER_BOOTSTRAP_PASSWORD")
        user_id = self.create_local_user(
            self.settings.bootstrap_admin,
            "系统管理员",
            self.settings.bootstrap_password,
            ["admin"],
        )
        self.audit.record("auth.bootstrap", "user", user_id, actor_name="system")

    @staticmethod
    def _hasher():
        from argon2 import PasswordHasher

        return PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2)

    def create_local_user(self, username: str, display_name: str, password: str, roles: list[str]) -> int:
        username = username.strip().lower()
        if len(username) < 3 or len(password) < 10:
            raise ValueError("用户名至少3个字符，密码至少10个字符")
        unknown = set(roles) - set(ROLE_PERMISSIONS)
        if unknown:
            raise ValueError(f"未知角色: {', '.join(sorted(unknown))}")
        password_hash = self._hasher().hash(password)
        with self.db.connect() as conn:
            cursor = conn.execute(
                "INSERT INTO app_users(username,display_name,password_hash,auth_source) VALUES (?,?,?,'local')",
                (username, display_name.strip() or username, password_hash),
            )
            user_id = int(cursor.lastrowid)
            for role in roles:
                conn.execute(
                    "INSERT INTO user_roles(user_id,role_id) SELECT ?,id FROM roles WHERE code=?",
                    (user_id, role),
                )
        return user_id

    def login(self, username: str, password: str, remote_address: str = "") -> dict[str, Any]:
        username = username.strip().lower()
        with self.db.connect() as conn:
            row = conn.execute("SELECT * FROM app_users WHERE username=?", (username,)).fetchone()
            recent_failures = int(
                conn.execute(
                    "SELECT COUNT(*) FROM login_attempts WHERE username=? AND succeeded=0 AND created_at>=?",
                    (username, _iso(_utc_now() - timedelta(minutes=15))),
                ).fetchone()[0]
            )
        if recent_failures >= 8:
            self.audit.record("auth.login", "user", username, outcome="blocked", details={"remote": remote_address})
            raise PermissionError("登录尝试过多，请15分钟后重试")
        valid = bool(row and row["is_active"] and row["auth_source"] == "local")
        if valid:
            try:
                self._hasher().verify(str(row["password_hash"]), password)
            except Exception:
                valid = False
        with self.db.connect() as conn:
            conn.execute(
                "INSERT INTO login_attempts(username,remote_address,succeeded) VALUES (?,?,?)",
                (username, remote_address[:200], int(valid)),
            )
        if not valid:
            self.audit.record("auth.login", "user", username, outcome="denied", details={"remote": remote_address})
            raise PermissionError("用户名或密码错误")
        session = self.create_session(int(row["id"]))
        self.audit.record("auth.login", "user", row["id"], actor_user_id=int(row["id"]), actor_name=username)
        return {**session, "user": self.get_user(int(row["id"]))}

    def create_session(self, user_id: int) -> dict[str, str]:
        token = secrets.token_urlsafe(48)
        csrf = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        expires = _utc_now() + timedelta(hours=12)
        with self.db.connect() as conn:
            conn.execute(
                "INSERT INTO auth_sessions(user_id,token_hash,csrf_token,expires_at) VALUES (?,?,?,?)",
                (user_id, token_hash, csrf, _iso(expires)),
            )
        return {"token": token, "csrf": csrf, "expires_at": _iso(expires)}

    def authenticate(self, token: str) -> dict[str, Any] | None:
        if not token:
            return None
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        with self.db.connect() as conn:
            row = conn.execute(
                """
                SELECT s.id AS session_id,s.csrf_token,s.expires_at,u.*
                FROM auth_sessions s JOIN app_users u ON u.id=s.user_id
                WHERE s.token_hash=? AND s.revoked_at IS NULL AND s.expires_at>? AND u.is_active=1
                """,
                (token_hash, _iso(_utc_now())),
            ).fetchone()
            if not row:
                return None
            conn.execute("UPDATE auth_sessions SET last_seen_at=CURRENT_TIMESTAMP WHERE id=?", (row["session_id"],))
        user = dict(row)
        user.update(self.get_user(int(row["id"])))
        return user

    def logout(self, token: str) -> None:
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        with self.db.connect() as conn:
            conn.execute("UPDATE auth_sessions SET revoked_at=CURRENT_TIMESTAMP WHERE token_hash=?", (token_hash,))

    def get_user(self, user_id: int) -> dict[str, Any]:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT id,username,display_name,auth_source,is_active FROM app_users WHERE id=?",
                (user_id,),
            ).fetchone()
            if not row:
                raise KeyError("用户不存在")
            roles = [
                str(item[0])
                for item in conn.execute(
                    "SELECT r.code FROM roles r JOIN user_roles ur ON ur.role_id=r.id WHERE ur.user_id=? ORDER BY r.code",
                    (user_id,),
                ).fetchall()
            ]
        payload = dict(row)
        payload["roles"] = roles
        return payload

    def list_users(self) -> list[dict[str, Any]]:
        rows = self.db.rows("SELECT id,username,display_name,auth_source,is_active,created_at,updated_at FROM app_users ORDER BY id")
        for row in rows:
            row["roles"] = self.get_user(int(row["id"]))["roles"]
        return rows

    def set_roles(self, user_id: int, roles: list[str], actor_user_id: int | None) -> dict[str, Any]:
        unknown = set(roles) - set(ROLE_PERMISSIONS)
        if not roles or unknown:
            raise ValueError("角色不能为空且必须使用受控角色")
        self.get_user(user_id)
        with self.db.connect() as conn:
            conn.execute("DELETE FROM user_roles WHERE user_id=?", (user_id,))
            for role in sorted(set(roles)):
                conn.execute("INSERT INTO user_roles(user_id,role_id) SELECT ?,id FROM roles WHERE code=?", (user_id, role))
        self.audit.record("auth.roles.update", "user", user_id, actor_user_id=actor_user_id, details={"roles": roles})
        return self.get_user(user_id)

    def set_active(self, user_id: int, active: bool, actor_user_id: int | None) -> dict[str, Any]:
        user = self.get_user(user_id)
        if not active and "admin" in user["roles"]:
            active_admins = self.db.row(
                """
                SELECT COUNT(DISTINCT u.id) AS count FROM app_users u
                JOIN user_roles ur ON ur.user_id=u.id JOIN roles r ON r.id=ur.role_id
                WHERE u.is_active=1 AND r.code='admin'
                """
            )
            if int((active_admins or {}).get("count", 0)) <= 1:
                raise ValueError("不能停用最后一个管理员")
        with self.db.connect() as conn:
            conn.execute("UPDATE app_users SET is_active=?,updated_at=CURRENT_TIMESTAMP WHERE id=?", (int(active), user_id))
            if not active:
                conn.execute("UPDATE auth_sessions SET revoked_at=CURRENT_TIMESTAMP WHERE user_id=? AND revoked_at IS NULL", (user_id,))
        self.audit.record("auth.user.active", "user", user_id, actor_user_id=actor_user_id, details={"active": active})
        return self.get_user(user_id)

    @staticmethod
    def allowed(user: dict[str, Any], permission: str) -> bool:
        permissions = set()
        for role in user.get("roles") or []:
            permissions.update(ROLE_PERMISSIONS.get(role, set()))
        return "*" in permissions or permission in permissions

    def oidc_start(self) -> str:
        if not self.settings.oidc_issuer or not self.settings.oidc_client_id:
            raise ValueError("OIDC未配置")
        metadata = httpx.get(f"{self.settings.oidc_issuer.rstrip('/')}/.well-known/openid-configuration", timeout=10).json()
        state = secrets.token_urlsafe(32)
        nonce = secrets.token_urlsafe(32)
        verifier = secrets.token_urlsafe(64)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
        with self.db.connect() as conn:
            conn.execute(
                "INSERT INTO oidc_states(state_hash,nonce,code_verifier,expires_at) VALUES (?,?,?,?)",
                (hashlib.sha256(state.encode()).hexdigest(), nonce, verifier, _iso(_utc_now() + timedelta(minutes=10))),
            )
        query = urlencode(
            {
                "response_type": "code",
                "client_id": self.settings.oidc_client_id,
                "redirect_uri": self.settings.oidc_redirect_uri,
                "scope": "openid profile email",
                "state": state,
                "nonce": nonce,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            }
        )
        return f"{metadata['authorization_endpoint']}?{query}"

    def oidc_callback(self, code: str, state: str) -> dict[str, Any]:
        state_hash = hashlib.sha256(state.encode()).hexdigest()
        with self.db.connect() as conn:
            stored = conn.execute(
                "SELECT * FROM oidc_states WHERE state_hash=? AND expires_at>?",
                (state_hash, _iso(_utc_now())),
            ).fetchone()
            if stored:
                conn.execute("DELETE FROM oidc_states WHERE id=?", (stored["id"],))
        if not stored:
            raise PermissionError("OIDC状态无效或已过期")
        metadata = httpx.get(f"{self.settings.oidc_issuer.rstrip('/')}/.well-known/openid-configuration", timeout=10).json()
        token_response = httpx.post(
            metadata["token_endpoint"],
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self.settings.oidc_redirect_uri,
                "client_id": self.settings.oidc_client_id,
                "client_secret": self.settings.oidc_client_secret,
                "code_verifier": stored["code_verifier"],
            },
            timeout=15,
        )
        token_response.raise_for_status()
        id_token = token_response.json()["id_token"]
        import jwt

        signing_key = jwt.PyJWKClient(metadata["jwks_uri"]).get_signing_key_from_jwt(id_token)
        claims = jwt.decode(
            id_token,
            signing_key.key,
            algorithms=metadata.get("id_token_signing_alg_values_supported") or ["RS256"],
            audience=self.settings.oidc_client_id,
            issuer=self.settings.oidc_issuer.rstrip("/"),
        )
        if claims.get("nonce") != stored["nonce"]:
            raise PermissionError("OIDC nonce校验失败")
        subject = str(claims["sub"])
        username = str(claims.get("preferred_username") or claims.get("email") or f"oidc-{subject[:12]}").lower()
        display_name = str(claims.get("name") or username)
        with self.db.connect() as conn:
            user = conn.execute("SELECT id FROM app_users WHERE oidc_subject=?", (subject,)).fetchone()
            if user:
                user_id = int(user[0])
            else:
                cursor = conn.execute(
                    "INSERT INTO app_users(username,display_name,auth_source,oidc_subject) VALUES (?,?,'oidc',?)",
                    (username, display_name, subject),
                )
                user_id = int(cursor.lastrowid)
                conn.execute(
                    "INSERT INTO user_roles(user_id,role_id) SELECT ?,id FROM roles WHERE code='viewer'",
                    (user_id,),
                )
        return {**self.create_session(user_id), "user": self.get_user(user_id)}

    @property
    def config(self) -> dict[str, Any]:
        return {"enabled": self.settings.auth_enabled, "oidc_enabled": bool(self.settings.oidc_issuer and self.settings.oidc_client_id)}
