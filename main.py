# main.py

from typing import List, Optional
from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel
from sqlmodel import Field, SQLModel, create_engine, Session, select
from contextlib import asynccontextmanager # <--- WAŻNY IMPORT

# --- 1. MODELE BAZY DANYCH (DEFINICJA STRUKTURY DANYCH) ---

class Uzytkownik(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    email: str = Field(index=True, unique=True)
    nazwa: str

class ListaZakupow(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    nazwa: str
    id_uzytkownika: int = Field(foreign_key="uzytkownik.id")

class PozycjaNaLiscie(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    nazwa_produktu: str
    id_listy: int = Field(foreign_key="listazakupow.id")


# --- 2. KONFIGURACJA APLIKACJI I BAZY DANYCH ---

DATABASE_URL = "sqlite:///database.db"
# connect_args jest ważny, by unikać błędów przy pracy z bazą SQLite w FastAPI
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})

def create_db_and_tables():
    SQLModel.metadata.create_all(engine)

# NOWA, POPRAWNA METODA OBSŁUGI STARTU APLIKACJI
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Kod, który uruchomi się przy starcie serwera
    print("Aplikacja startuje, tworzę tabele w bazie danych...")
    create_db_and_tables()
    yield
    # Kod, który mógłby uruchomić się przy zamykaniu serwera
    print("Aplikacja się zamyka.")

# Inicjalizacja FastAPI z użyciem nowej metody `lifespan`
app = FastAPI(title="CenoSkoczek API", version="1.0.0", lifespan=lifespan)

# Funkcja pomocnicza do zarządzania sesją z bazą danych
def get_session():
    with Session(engine) as session:
        yield session


# --- 3. "DRZWI" DO APLIKACJI (API ENDPOINTS) ---

# Endpoint do tworzenia użytkownika (wersja uproszczona)
@app.post("/uzytkownicy/", response_model=Uzytkownik)
def create_user(user: Uzytkownik, session: Session = Depends(get_session)):
    existing_user = session.exec(select(Uzytkownik).where(Uzytkownik.email == user.email)).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="Użytkownik z tym adresem email już istnieje.")
    session.add(user)
    session.commit()
    session.refresh(user)
    return user

# Endpoint do tworzenia listy zakupów
@app.post("/listy-zakupow/", response_model=ListaZakupow)
def create_shopping_list(lista: ListaZakupow, session: Session = Depends(get_session)):
    user = session.get(Uzytkownik, lista.id_uzytkownika)
    if not user:
        raise HTTPException(status_code=404, detail="Nie znaleziono użytkownika o podanym ID.")
    session.add(lista)
    session.commit()
    session.refresh(lista)
    return lista

# Endpoint do dodawania produktu do listy
@app.post("/listy-zakupow/{id_listy}/pozycje/", response_model=PozycjaNaLiscie)
def add_item_to_list(id_listy: int, pozycja: PozycjaNaLiscie, session: Session = Depends(get_session)):
    lista = session.get(ListaZakupow, id_listy)
    if not lista:
        raise HTTPException(status_code=404, detail="Nie znaleziono listy o podanym ID.")
    pozycja.id_listy = id_listy
    session.add(pozycja)
    session.commit()
    session.refresh(pozycja)
    return pozycja

# Endpoint do pobierania produktów z listy
@app.get("/listy-zakupow/{id_listy}/pozycje/", response_model=List[PozycjaNaLiscie])
def get_items_from_list(id_listy: int, session: Session = Depends(get_session)):
    pozycje = session.exec(select(PozycjaNaLiscie).where(PozycjaNaLiscie.id_listy == id_listy)).all()
    return pozycje

# Endpoint do porównywania cen (z przykładowymi danymi)
class ShoppingListRequest(BaseModel):
    products: list[str]

def scrape_price_from_store(product_name: str, store_name: str) -> float | None:
    # To jest atrapa (mock) - w rzeczywistości tu byłby prawdziwy web scraping
    prices = {
        "Biedronka": {"mleko": 3.50, "chleb": 4.00, "jajka": 8.00},
        "Lidl": {"mleko": 3.60, "chleb": 3.90, "jajka": 8.50},
        "Auchan": {"mleko": 3.40, "chleb": 4.20, "jajka": 7.80}
    }
    return prices.get(store_name, {}).get(product_name.lower())

@app.post("/porownaj-ceny/")
def compare_prices(request: ShoppingListRequest):
    stores = ["Biedronka", "Lidl", "Auchan"]
    results = {}
    for store in stores:
        total_cost = 0
        found_products = 0
        for product in request.products:
            price = scrape_price_from_store(product, store)
            if price is not None:
                total_cost += price
                found_products += 1
        if found_products > 0:
            results[store] = {
                "total_cost": round(total_cost, 2),
                "found_products": found_products,
                "total_products": len(request.products)
            }
    sorted_results = sorted(results.items(), key=lambda item: item[1]['total_cost'])
    return dict(sorted_results)

# Startowy endpoint
@app.get("/")
def read_root():
    return {"Wiadomość": "Witaj w API aplikacji CenoSkoczek!"}