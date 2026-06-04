from fastapi import APIRouter, HTTPException, Depends, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel, EmailStr
from passlib.context import CryptContext
from jose import JWTError, jwt
from datetime import datetime, timedelta
from typing import Optional
import sys, os
sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from database import get_db

router = APIRouter(prefix="/auth", tags=["auth"])

SECRET_KEY = "aftervisit_secret_key_2026_nagpur"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 24

pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

# ── SCHEMAS ──────────────────────────────────────────────────────
class RegisterRequest(BaseModel):
    name: str
    email: str
    phone: Optional[str] = None
    password: str
    role: str = "patient"
    city: Optional[str] = None

class LoginResponse(BaseModel):
    access_token: str
    token_type: str
    user_id: int
    name: str
    role: str
    email: str

class UserOut(BaseModel):
    id: int
    name: str
    email: str
    role: str
    city: Optional[str]
    hospital_id: Optional[int]

# ── HELPERS ───────────────────────────────────────────────────────
def hash_password(password: str) -> str:
    return pwd_ctx.hash(password)

def verify_password(plain: str, hashed: str) -> bool:
    return pwd_ctx.verify(plain, hashed)

def create_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def get_current_user(token: str = Depends(oauth2_scheme)) -> dict:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: int = payload.get("user_id")
        role: str = payload.get("role")
        if user_id is None:
            raise credentials_exception
        return {"user_id": user_id, "role": role}
    except JWTError:
        raise credentials_exception

def require_doctor(current_user: dict = Depends(get_current_user)) -> dict:
    if current_user["role"] not in ["doctor", "admin"]:
        raise HTTPException(status_code=403, detail="Doctor access required")
    return current_user

def require_patient(current_user: dict = Depends(get_current_user)) -> dict:
    if current_user["role"] != "patient":
        raise HTTPException(status_code=403, detail="Patient access required")
    return current_user

# ── ROUTES ────────────────────────────────────────────────────────
@router.post("/register", response_model=LoginResponse)
def register(req: RegisterRequest):
    db = get_db()
    try:
        # Check if email exists
        existing = db.execute("SELECT id FROM users WHERE email = ?", (req.email,)).fetchone()
        if existing:
            raise HTTPException(status_code=400, detail="Email already registered")

        if req.role not in ["patient", "doctor"]:
            raise HTTPException(status_code=400, detail="Invalid role")

        # Insert user
        db.execute("""
            INSERT INTO users (name, email, phone, password, role, city)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (req.name, req.email, req.phone, hash_password(req.password), req.role, req.city))
        db.commit()

        user = db.execute("SELECT * FROM users WHERE email = ?", (req.email,)).fetchone()

        # If patient, create patient profile
        if req.role == "patient":
            db.execute("INSERT INTO patients (user_id) VALUES (?)", (user["id"],))
            db.commit()

        token = create_token({"user_id": user["id"], "role": user["role"], "email": user["email"]})
        return LoginResponse(
            access_token=token, token_type="bearer",
            user_id=user["id"], name=user["name"],
            role=user["role"], email=user["email"]
        )
    finally:
        db.close()

@router.post("/login", response_model=LoginResponse)
def login(form: OAuth2PasswordRequestForm = Depends()):
    db = get_db()
    try:
        user = db.execute("SELECT * FROM users WHERE email = ?", (form.username,)).fetchone()
        if not user or not verify_password(form.password, user["password"]):
            raise HTTPException(status_code=401, detail="Invalid email or password")
        if not user["is_active"]:
            raise HTTPException(status_code=403, detail="Account deactivated")

        token = create_token({"user_id": user["id"], "role": user["role"], "email": user["email"]})
        return LoginResponse(
            access_token=token, token_type="bearer",
            user_id=user["id"], name=user["name"],
            role=user["role"], email=user["email"]
        )
    finally:
        db.close()

@router.post("/demo-login/{role}", response_model=LoginResponse)
def demo_login(role: str):
    """Quick demo login — no password needed"""
    db = get_db()
    try:
        email_map = {"patient": "patient@aftervisit.site", "doctor": "doctor@aftervisit.site"}
        if role not in email_map:
            raise HTTPException(status_code=400, detail="Invalid role. Use 'patient' or 'doctor'")
        
        user = db.execute("SELECT * FROM users WHERE email = ?", (email_map[role],)).fetchone()
        if not user:
            raise HTTPException(status_code=404, detail="Demo user not found. Run seed first.")

        token = create_token({"user_id": user["id"], "role": user["role"], "email": user["email"]})
        return LoginResponse(
            access_token=token, token_type="bearer",
            user_id=user["id"], name=user["name"],
            role=user["role"], email=user["email"]
        )
    finally:
        db.close()

@router.get("/me", response_model=UserOut)
def get_me(current_user: dict = Depends(get_current_user)):
    db = get_db()
    try:
        user = db.execute("SELECT * FROM users WHERE id = ?", (current_user["user_id"],)).fetchone()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        return dict(user)
    finally:
        db.close()
