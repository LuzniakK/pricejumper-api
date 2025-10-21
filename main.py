# main.py
from typing import List, Optional, Dict
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
# --- POPRAWKA TUTAJ: Dodajemy argument `connect_args` ---
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False, "timeout": 15})

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

STORE_CONFIGS = {
    "Frisco.pl": {
        "search_url": "https://www.frisco.pl/szukaj/{query}",
        "price_selector": "div[data-qa^='final-price'] span.price",
        "product_mapping": { "mleko": "mleko%20łaciate", "chleb": "chleb%20wiejski" }
    },
    "Auchan Zakupy": {
        "search_url": "https://www.auchandirect.pl/auchan-pl/search/{query}",
        "price_selector": "div[class*='-priceValue']",
        "product_mapping": { "mleko": "mleko%20uht", "chleb": "chleb%20tradycyjny" }
    }
}

def scrape_price(product_query: str, config: dict) -> Optional[float]:
    try:
        url = config["search_url"].format(query=product_query)
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code != 200:
            return None
        soup = BeautifulSoup(response.text, 'html.parser')
        price_element = soup.select_one(config["price_selector"])
        if price_element:
            price_text = price_element.get_text()
            match = re.search(r'(\d+[,.]\d{1,2})', price_text)
            if match:
                return float(match.group(1).replace(',', '.'))
        return None
    except Exception:
        return None

# --- 4. ENDPOINTS API ---

def get_or_create_list(device_id: str, session: Session) -> ShoppingList:
    shopping_list = session.exec(select(ShoppingList).where(ShoppingList.device_id == device_id)).first()
    if not shopping_list:
        shopping_list = ShoppingList(device_id=device_id)
        session.add(shopping_list)
        session.commit()
        session.refresh(shopping_list)
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

@app.post("/compare")
def compare_prices(request: ComparisonRequest):
    results: Dict[str, dict] = {}
    for store_name, config in STORE_CONFIGS.items():
        total_cost = 0.0
        found_products_count = 0
        for product in request.products:
            product_lower = product.lower()
            query = product.replace(" ", "%20")
            for keyword, mapped_query in config["product_mapping"].items():
                if keyword in product_lower:
                    query = mapped_query
                    break
            price = scrape_price(query, config)
            if price:
                total_cost += price
                found_products_count += 1
        if found_products_count > 0:
            results[store_name] = {
                "total_cost": round(total_cost, 2),
                "found_products": f"{found_products_count}/{len(request.products)}"
            }
    sorted_results = sorted(results.items(), key=lambda item: item[1]['total_cost'])
    return dict(sorted_results)