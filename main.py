from pathlib import Path
import networkx as nx
import pandas as pd
from sqlalchemy import create_engine
import yaml

DB_HOST = "192.168.101.210"
DB_USER = "Adam"
DB_PASS = ""
DB_NAME = "task4"

engine = create_engine(
    f"mysql+mysqlconnector://{DB_USER}:{DB_PASS}@{DB_HOST}/{DB_NAME}"
)

CURRENCY_MAP = {"€": "EUR", "$": "USD"}


def clean_price(price):
  if price is None:
    return None, "USD"
  price_str = str(price)
  currency = next(
      (curr for sym, curr in CURRENCY_MAP.items() if sym in price_str), "USD"
  )
  cleaned = pd.Series([price_str]).str.replace(r"[^\d.]", "", regex=True)[0]
  return float(cleaned) if cleaned else None, currency


def reconcile_users(users_df):
  users_df["clean_phone"] = users_df["phone"].str.replace(
      r"\D", "", regex=True
  )
  G = nx.Graph()
  for uid in users_df["user_id"]:
    G.add_node(uid)

  records = users_df.to_dict("records")
  for i in range(len(records)):
    for j in range(i + 1, len(records)):
      r1, r2 = records[i], records[j]
      matches = sum([
          r1["name"] == r2["name"],
          r1["email"] == r2["email"],
          r1["address"] == r2["address"],
          r1["clean_phone"] == r2["clean_phone"],
      ])
      if matches >= 3:
        G.add_edge(r1["user_id"], r2["user_id"])

  user_to_real = {}
  for comp in nx.connected_components(G):
    real_id = min(comp)
    for uid in comp:
      user_to_real[uid] = real_id

  users_df["real_user_id"] = users_df["user_id"].map(user_to_real)
  return users_df


def process_and_load_store(folder_name, is_first_store):
  print(f"\nProcessing folder: {folder_name}")
  folder_path = Path(folder_name)

  try:
    orders_path = folder_path / "orders.parquet"
    users_path = folder_path / "users.csv"
    books_path = folder_path / "books.yaml"

    if not (
        orders_path.exists() and users_path.exists() and books_path.exists()
    ):
      print(f"Missing required files in {folder_name}. Skipping.")
      return

    orders_df = pd.read_parquet(orders_path)

    orders_df.columns = [c.lower().strip() for c in orders_df.columns]
    column_mapping = {
        "time": "timestamp",
        "datetime": "timestamp",
        "userid": "user_id",
        "user": "user_id",
        "bookid": "book_id",
        "book": "book_id",
        "qty": "quantity",
        "price": "unit_price",
        "unitprice": "unit_price",
        "curr": "currency",
    }
    orders_df = orders_df.rename(columns=column_mapping)

    users_df = pd.read_csv(
        users_path,
        header=None,
        names=["user_id", "name", "address", "phone", "email"],
    )

    users_df = users_df[users_df["user_id"] != "user_id"]

    with open(books_path, "r", encoding="utf-8") as f:
      raw_books = yaml.safe_load(f)

    books_list = []
    for book in raw_books:
      clean_book = {k.lstrip(":"): v for k, v in book.items()}
      raw_price = clean_book.get("price")
      parsed_price, currency = clean_price(raw_price)

      author_raw = clean_book.get("author") or clean_book.get("authors", "")
      if isinstance(author_raw, str):
        authors_list = [
            a.strip() for a in author_raw.replace("&", ",").split(",") if a.strip()
        ]
      elif isinstance(author_raw, list):
        authors_list = [str(a).strip() for a in author_raw]
      else:
        authors_list = ["Unknown"]

      author_set_str = ", ".join(sorted(authors_list))

      books_list.append({
          "id": clean_book.get("id"),
          "title": clean_book.get("title"),
          "author": author_set_str,
          "genre": clean_book.get("genre"),
          "publisher": clean_book.get("publisher"),
          "year": clean_book.get("year"),
          "price": parsed_price,
          "currency": currency,
          "store_name": folder_name,
      })
    books_df = pd.DataFrame(books_list)

    users_df = users_df.drop_duplicates(subset=["user_id"])
    users_df = reconcile_users(users_df)
    users_df["store_name"] = folder_name

    orders_df = orders_df.drop_duplicates()
    print(f"  - Initial orders rows: {len(orders_df)}")

    if "timestamp" in orders_df.columns:
        orders_df["timestamp"] = pd.to_datetime(
            orders_df["timestamp"],
            format="mixed",
            utc=True,
            errors="coerce"
        )
    else:
      orders_df["timestamp"] = pd.NaT

    orders_df = orders_df.dropna(subset=["timestamp", "user_id", "book_id"])

    if "quantity" in orders_df.columns:
      orders_df["quantity"] = (
          orders_df["quantity"]
          .astype(str)
          .str.replace(r"[^\d.]", "", regex=True)
      )
      orders_df["quantity"] = pd.to_numeric(
          orders_df["quantity"], errors="coerce"
      )
    else:
      orders_df["quantity"] = 1.0

    if "unit_price" in orders_df.columns:
      orders_df["unit_price"] = (
          orders_df["unit_price"]
          .astype(str)
          .str.replace(r"[^\d.]", "", regex=True)
      )
      orders_df["unit_price"] = pd.to_numeric(
          orders_df["unit_price"], errors="coerce"
      )
    else:
      orders_df["unit_price"] = 0.0

    orders_df = orders_df.dropna(subset=["quantity", "unit_price"])
    print(f"Valid orders rows after cleaning: {len(orders_df)}")
    orders_df["date"] = orders_df["timestamp"].dt.strftime("%Y-%m-%d")

    if "currency" not in orders_df.columns:
      orders_df["currency"] = "USD"

    mult_map = {"EUR": 1.2, "USD": 1.0, "GBP": 1.3}
    multiplier = orders_df["currency"].map(mult_map).fillna(1.0)
    orders_df["paid_price"] = round(
        orders_df["quantity"] * orders_df["unit_price"] * multiplier, 2)

    orders_df["store_name"] = folder_name
    table_mode = "replace" if is_first_store else "append"

    orders_df.to_sql("orders", con=engine, if_exists=table_mode, index=False, chunksize=1000)
    users_df.to_sql("users", con=engine, if_exists=table_mode, index=False, chunksize=1000)
    books_df.to_sql("books", con=engine, if_exists=table_mode, index=False, chunksize=1000)
    print(f"Successfully loaded data from {folder_name} into database using"
          f" mode='{table_mode}'.")
  except Exception as e:
    print(f"Error processing {folder_name}: {e}")

def main():
  stores = ["STORE1", "STORE2", "STORE3", "STORE4", "STORE5"]
  for idx, store in enumerate(stores):
    if Path(store).exists():
      is_first = idx == 0
      process_and_load_store(store, is_first)

if __name__ == "__main__":
  main()