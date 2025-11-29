# Para rodar: uvicorn main:app --reload
# http://127.0.0.1:8000/docs
import os
import re
import uuid
from typing import Optional, List
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, validator
from datetime import datetime


USE_MONGO = False
MONGO_URI = os.getenv("MONGO_URI")  
if MONGO_URI:
    try:
        from pymongo import MongoClient
        client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
        db = client.get_database("shared_resources")
        client.server_info()
        USE_MONGO = True
        print("Usando MongoDB:", MONGO_URI)
    except Exception as e:
        print("Não foi possível conectar ao MongoDB (vai usar memória):", e)
        USE_MONGO = False
else:
    print("MONGO_URI não definido — usando armazenamento em memória.")


POINTS_FOR_LENDING = 10
POINTS_FOR_BORROW = 5


class UserCreate(BaseModel):
    name: str = Field(..., min_length=1)
    email: str


    @validator("email")
    def simple_email(cls, v):
        if not re.match(r"[^@]+@[^@]+\.[^@]+", v):
            raise ValueError("email inválido")
        return v.lower().strip()


class UserOut(UserCreate):
    id: str
    points: int


class ItemCreate(BaseModel):
    name: str = Field(..., min_length=1)
    description: Optional[str] = None
    owner_id: str


class ItemOut(ItemCreate):
    id: str
    available: bool


class LoanCreate(BaseModel):
    item_id: str
    borrower_id: str


_mem_users = {}
_mem_items = {}
_mem_loans = {}


def _new_id() -> str:
    return str(uuid.uuid4())


def create_user_store(user: UserCreate) -> dict:
    doc = {"name": user.name, "email": user.email, "points": 0, "created_at": datetime.utcnow().isoformat()}
    if USE_MONGO:
        res = db.users.insert_one(doc)
        doc["id"] = str(res.inserted_id)
    else:
        doc["id"] = _new_id()
        _mem_users[doc["id"]] = doc
    return {"id": doc["id"], "name": doc["name"], "email": doc["email"], "points": doc["points"]}


def list_users_store() -> List[dict]:
    if USE_MONGO:
        users = []
        for u in db.users.find({}):
            users.append({"id": str(u.get("_id")), "name": u.get("name"), "email": u.get("email"), "points": u.get("points", 0)})
        return users
    else:
        return [{"id": k, "name": v["name"], "email": v["email"], "points": v.get("points", 0)} for k, v in _mem_users.items()]


def get_user_store(user_id: str) -> Optional[dict]:
    if USE_MONGO:
        u = db.users.find_one({"_id": user_id})  
        if u:
            return {"id": str(u.get("_id")), "name": u.get("name"), "email": u.get("email"), "points": u.get("points", 0)}
        return None
    else:
        return _mem_users.get(user_id)


def update_user_points(user_id: str, delta: int) -> bool:
    if USE_MONGO:
        res = db.users.update_one({"_id": user_id}, {"$inc": {"points": delta}})
        return res.matched_count > 0
    else:
        u = _mem_users.get(user_id)
        if not u:
            return False
        u["points"] = u.get("points", 0) + delta
        return True


def create_item_store(item: ItemCreate) -> dict:
    doc = {"name": item.name, "description": item.description, "owner_id": item.owner_id, "available": True, "created_at": datetime.utcnow().isoformat()}
    if USE_MONGO:
        res = db.items.insert_one(doc)
        doc["id"] = str(res.inserted_id)
    else:
        doc["id"] = _new_id()
        _mem_items[doc["id"]] = doc
    return {"id": doc["id"], "name": doc["name"], "description": doc["description"], "owner_id": doc["owner_id"], "available": doc["available"]}


def list_items_store() -> List[dict]:
    if USE_MONGO:
        items = []
        for i in db.items.find({}):
            items.append({"id": str(i.get("_id")), "name": i.get("name"), "description": i.get("description"), "owner_id": i.get("owner_id"), "available": i.get("available", True)})
        return items
    else:
        return [{"id": k, "name": v["name"], "description": v.get("description"), "owner_id": v["owner_id"], "available": v.get("available", True)} for k, v in _mem_items.items()]


def get_item_store(item_id: str) -> Optional[dict]:
    if USE_MONGO:
        i = db.items.find_one({"_id": item_id})
        if i:
            return {"id": str(i.get("_id")), "name": i.get("name"), "description": i.get("description"), "owner_id": i.get("owner_id"), "available": i.get("available", True)}
        return None
    else:
        return _mem_items.get(item_id)


def set_item_availability(item_id: str, available: bool) -> bool:
    if USE_MONGO:
        res = db.items.update_one({"_id": item_id}, {"$set": {"available": available}})
        return res.matched_count > 0
    else:
        it = _mem_items.get(item_id)
        if not it:
            return False
        it["available"] = available
        return True


def create_loan_store(loan: LoanCreate) -> dict:
    doc = {"item_id": loan.item_id, "borrower_id": loan.borrower_id, "borrowed_at": datetime.utcnow().isoformat()}
    if USE_MONGO:
        res = db.loans.insert_one(doc)
        doc["id"] = str(res.inserted_id)
    else:
        doc["id"] = _new_id()
        _mem_loans[doc["id"]] = doc
    return doc



app = FastAPI(title="Plataforma de Compartilhamento (simples)")


@app.post("/users/", response_model=UserOut)
def create_user(user: UserCreate):
    u = create_user_store(user)
    return u


@app.get("/users/", response_model=List[UserOut])
def list_users():
    return list_users_store()


@app.post("/items/", response_model=ItemOut)
def create_item(item: ItemCreate):

    owner = get_user_store(item.owner_id)
    if not owner:
        raise HTTPException(status_code=404, detail="owner_id não encontrado")


    i = create_item_store(item)

    update_user_points(item.owner_id, POINTS_FOR_LENDING)
    return i


@app.get("/items/", response_model=List[ItemOut])
def list_items():
    return list_items_store()


@app.post("/loans/")
def borrow_item(loan: LoanCreate):
    item = get_item_store(loan.item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item não encontrado")
    if not item.get("available", True):
        raise HTTPException(status_code=409, detail="Item já está emprestado")


    borrower = get_user_store(loan.borrower_id)
    if not borrower:
        raise HTTPException(status_code=404, detail="Usuário (borrower_id) não encontrado")


    if borrower.get("points", 0) < POINTS_FOR_BORROW:
        raise HTTPException(status_code=403, detail="Pontos insuficientes para pegar emprestado")


    ok = set_item_availability(loan.item_id, False)
    if not ok:
        raise HTTPException(status_code=500, detail="Erro ao atualizar item")


    update_user_points(loan.borrower_id, -POINTS_FOR_BORROW)


    create_loan_store(loan)


    return {"status": "item emprestado com sucesso"}


@app.post("/loans/return/{item_id}")
def return_item(item_id: str):
    item = get_item_store(item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item não encontrado")


    ok = set_item_availability(item_id, True)
    if not ok:
        raise HTTPException(status_code=500, detail="Erro ao atualizar item")


    return {"status": "item devolvido com sucesso"}


@app.get("/health")
def health():
    return {"status": "ok", "storage": "mongo" if USE_MONGO else "memory"}
