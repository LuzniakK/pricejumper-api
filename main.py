# main.py
from typing import List, Optional, Annotated
from fastapi import FastAPI, HTTPException, Depends
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel
from sqlmodel import Field, SQLModel, create_engine, Session, select
from contextlib import asynccontextmanager
from passlib.context import CryptContext
from jose import JWTError, jwt
from datetime import datetime, timedelta, timezone

# --- 1. KONFIGURACJA BEZPIECZEŃSTWA ---
SECRET_KEY = "TWOJ_BARDZO_TAJNY_KLUCZ_KTORY_POWINIENES_ZMIENIC"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

# --- 2. FUNKCJE POMOCNICZE DO BEZPIECZEŃSTWA ---
def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)
def get_password_hash(password):
    return pwd_context.hash(password)
def create_access_token(data: dict, expires_delta: timedelta | None = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

# --- 3. MODELE DANYCH ---
class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    email: str = Field(unique=True, index=True)
    hashed_password: str

class ShoppingList(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    owner_id: int = Field(foreign_key="user.id")

class ListItem(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    product_name: str
    list_id: int = Field(foreign_key="shoppinglist.id")

class UserCreate(BaseModel):
    email: str
    password: str
class ListItemCreate(BaseModel):
    product_name: str
class Token(BaseModel):
    access_token: str
    token_type: str

# --- 4. KONFIGURACJA APLIKACJI I BAZY DANYCH ---
DATABASE_URL = "sqlite:///database.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})

def create_db_and_tables():
    SQLModel.metadata.create_all(engine)

@asynccontextmanager
async def lifespan(app: FastAPI):
    create_db_and_tables()
    yield

app = FastAPI(lifespan=lifespan)

def get_session():
    with Session(engine) as session:
        yield session

# --- 5. FUNKCJA POBIERANIA AKTUALNEGO UŻYTKOWNIKA ---
async def get_current_user(token: Annotated[str, Depends(oauth2_scheme)], session: Session = Depends(get_session)):
    credentials_exception = HTTPException(status_code=401, detail="Could not validate credentials", headers={"WWW-Authenticate": "Bearer"})
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        if email is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    user = session.exec(select(User).where(User.email == email)).first()
    if user is None:
        raise credentials_exception
    return user

# --- 6. ENDPOINTS API ---
@app.post("/register", response_model=User)
def register_user(user_data: UserCreate, session: Session = Depends(get_session)):
    db_user = session.exec(select(User).where(User.email == user_data.email)).first()
    if db_user:
        raise HTTPException(status_code=400, detail="Email already registered")
    hashed_password = get_password_hash(user_data.password)
    new_user = User(email=user_data.email, hashed_password=hashed_password)
    session.add(new_user)
    session.commit()
    session.refresh(new_user)
    # Po rejestracji, stwórz dla użytkownika jego pierwszą listę zakupów
    new_list = ShoppingList(name=f"Lista zakupów {new_user.email}", owner_id=new_user.id)
    session.add(new_list)
    session.commit()
    return new_user

@app.post("/token", response_model=Token)
async def login_for_access_token(form_data: Annotated[OAuth2PasswordRequestForm, Depends()], session: Session = Depends(get_session)):
    user = session.exec(select(User).where(User.email == form_data.username)).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Incorrect email or password", headers={"WWW-Authenticate": "Bearer"})
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(data={"sub": user.email}, expires_delta=access_token_expires)
    return {"access_token": access_token, "token_type": "bearer"}

@app.get("/users/me", response_model=User)
async def read_users_me(current_user: Annotated[User, Depends(get_current_user)]):
    return current_user

# --- ENDPOINTY DO OBSŁUGI LIST ---
@app.get("/shopping-lists/my-list", response_model=List[ListItem])
async def get_my_shopping_list_items(current_user: Annotated[User, Depends(get_current_user)], session: Session = Depends(get_session)):
    shopping_list = session.exec(select(ShoppingList).where(ShoppingList.owner_id == current_user.id)).first()
    if not shopping_list:
        # Jeśli użytkownik nie ma listy, stwórz ją
        shopping_list = ShoppingList(name=f"Lista zakupów {current_user.email}", owner_id=current_user.id)
        session.add(shopping_list)
        session.commit()
        session.refresh(shopping_list)
    items = session.exec(select(ListItem).where(ListItem.list_id == shopping_list.id)).all()
    return items

@app.post("/shopping-lists/my-list/items", response_model=ListItem)
async def add_item_to_my_list(item_data: ListItemCreate, current_user: Annotated[User, Depends(get_current_user)], session: Session = Depends(get_session)):
    shopping_list = session.exec(select(ShoppingList).where(ShoppingList.owner_id == current_user.id)).first()
    if not shopping_list:
        raise HTTPException(status_code=404, detail="Shopping list not found for user")
    new_item = ListItem(product_name=item_data.product_name, list_id=shopping_list.id)
    session.add(new_item)
    session.commit()
    session.refresh(new_item)
    return new_item