# main.py

from typing import List, Optional
from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel
from sqlmodel import Field, SQLModel, create_engine, Session, select
from contextlib import asynccontextmanager

# --- 1. MODELE DANYCH ---

class ShoppingList(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    device_id: str = Field(unique=True, index=True)

class ListItem(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    product_name: str
    list_id: int = Field(foreign_key="shoppinglist.id")

class ListItemCreate(BaseModel):
    product_name: str

# --- 2. KONFIGURACJA APLIKACJI I BAZY DANYCH ---

# ZMIANA NAZWY BAZY DANYCH
DATABASE_URL = "sqlite:///database_v2.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})

def create_db_and_tables():
    SQLModel.metadata.create_all(engine)

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Aplikacja startuje, tworzę tabele...")
    create_db_and_tables()
    yield
    print("Aplikacja się zamyka.")

app = FastAPI(title="CenoSkoczek API v2", version="2.0.0", lifespan=lifespan)

def get_session():
    with Session(engine) as session:
        yield session

# --- 3. ENDPOINTS API ---

def get_or_create_list(device_id: str, session: Session) -> ShoppingList:
    shopping_list = session.exec(select(ShoppingList).where(ShoppingList.device_id == device_id)).first()
    if not shopping_list:
        print(f"Nie znaleziono listy dla urządzenia {device_id}, tworzę nową...")
        shopping_list = ShoppingList(device_id=device_id)
        session.add(shopping_list)
        session.commit()
        session.refresh(shopping_list)
        print("Nowa lista stworzona.")
    return shopping_list

@app.get("/shopping-list/{device_id}", response_model=List[ListItem])
def get_shopping_list_items(device_id: str, session: Session = Depends(get_session)):
    shopping_list = get_or_create_list(device_id, session)
    items = session.exec(select(ListItem).where(ListItem.list_id == shopping_list.id)).all()
    return items

@app.post("/shopping-list/{device_id}/items", response_model=ListItem)
def add_item_to_list(device_id: str, item_data: ListItemCreate, session: Session = Depends(get_session)):
    shopping_list = get_or_create_list(device_id, session)
    new_item = ListItem(product_name=item_data.product_name, list_id=shopping_list.id)
    session.add(new_item)
    session.commit()
    session.refresh(new_item)
    return new_item