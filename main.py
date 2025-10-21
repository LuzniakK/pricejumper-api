# main.py
from typing import List, Optional
from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel
from sqlmodel import Field, SQLModel, create_engine, Session, select
from contextlib import asynccontextmanager
import requests
from bs4 import BeautifulSoup
import re

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

class ComparisonRequest(BaseModel):
    products: List[str]

# --- 2. KONFIGURACJA APLIKACJI I BAZY DANYCH ---

DATABASE_URL = "sqlite:///database_v2.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})

def create_db_and_tables():
    SQLModel.metadata.create_all(engine)

@asynccontextmanager
async def lifespan(app: FastAPI):
    create_db_and_tables()
    yield

app = FastAPI(title="CenoSkoczek API v2", version="2.0.0", lifespan=lifespan)

def get_session():
    with Session(engine) as session:
        yield session

# --- 3. LOGIKA WEB SCRAPINGU ---

def scrape_page_for_price(product_name: str, store_config: dict) -> Optional[float]:
    """
    Odwiedza stronę produktu i próbuje wyciągnąć z niej cenę.
    """
    try:
        search_url = store_config["search_url"].format(query=product_name.replace(" ", "+"))
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        
        response = requests.get(search_url, headers=headers, timeout=5)
        if response.status_code != 200:
            return None

        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Używamy selektora CSS zdefiniowanego w konfiguracji sklepu
        price_element = soup.select_one(store_config["price_selector"])
        
        if price_element:
            price_text = price_element.get_text()
            match = re.search(r'(\d+[,.]\d{2})', price_text)
            if match:
                return float(match.group(1).replace(',', '.'))
        
        return None
    except requests.exceptions.RequestException:
        return None # Błąd połączenia lub timeout
    except Exception:
        return None # Inny błąd parsowania

# --- 4. ENDPOINTS API ---

def get_or_create_list(device_id: str, session: Session) -> ShoppingList:
    # ... (bez zmian)
    shopping_list = session.exec(select(ShoppingList).where(ShoppingList.device_id == device_id)).first()
    if not shopping_list:
        shopping_list = ShoppingList(device_id=device_id)
        session.add(shopping_list)
        session.commit()
        session.refresh(shopping_list)
    return shopping_list

@app.get("/shopping-list/{device_id}", response_model=List[ListItem])
def get_shopping_list_items(device_id: str, session: Session = Depends(get_session)):
    # ... (bez zmian)
    shopping_list = get_or_create_list(device_id, session)
    items = session.exec(select(ListItem).where(ListItem.list_id == shopping_list.id)).all()
    return items

@app.post("/shopping-list/{device_id}/items", response_model=ListItem)
def add_item_to_list(device_id: str, item_data: ListItemCreate, session: Session = Depends(get_session)):
    # ... (bez zmian)
    shopping_list = get_or_create_list(device_id, session)
    new_item = ListItem(product_name=item_data.product_name, list_id=shopping_list.id)
    session.add(new_item)
    session.commit()
    session.refresh(new_item)
    return new_item

@app.post("/compare")
def compare_prices(request: ComparisonRequest):
    # Przykładowa konfiguracja dla dwóch sklepów (w rzeczywistości byłaby bardziej złożona)
    # Używamy publicznych API do testów, które symulują strony sklepów
    stores_config = {
        "Sklep A (Testowy)": {
            "search_url": "https://dummyjson.com/products/search?q={query}",
            "price_selector": ".price" # To jest zmyślony selektor dla przykładu
        },
        "Sklep B (Testowy)": {
            "search_url": "https://api.escuelajs.co/api/v1/products/?title={query}",
            "price_selector": ".card-title" # To jest zmyślony selektor dla przykładu
        }
    }
    
    # UWAGA: Prawdziwe strony sklepów blokują takie zapytania. To jest tylko model koncepcyjny.
    # W `dummyjson.com` cena jest w `price`, w `escuelajs` w `title`. To pokazuje, jak różne są strony.
    
    results = {}
    for store_name, config in stores_config.items():
        total_cost = 0.0
        found_products_count = 0
        
        # W tym przykładzie nie scrapujemy, tylko używamy atrap, by pokazać logikę
        if store_name == "Sklep A (Testowy)":
            if "mleko" in request.products: total_cost += 3.50; found_products_count += 1
            if "chleb" in request.products: total_cost += 4.00; found_products_count += 1
        if store_name == "Sklep B (Testowy)":
            if "mleko" in request.products: total_cost += 3.60; found_products_count += 1
            if "chleb" in request.products: total_cost += 4.20; found_products_count += 1

        if found_products_count > 0:
            results[store_name] = {
                "total_cost": round(total_cost, 2),
                "found_products": f"{found_products_count}/{len(request.products)}"
            }

    sorted_results = sorted(results.items(), key=lambda item: item[1]['total_cost'])
    return dict(sorted_results)