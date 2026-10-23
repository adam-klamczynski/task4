import pandas as pd
from sqlalchemy import create_engine
import streamlit as st

DB_HOST = "192.168.101.210"
DB_USER = "Adam"
DB_PASS = ""
DB_NAME = "task4"

engine = create_engine(
    f"mysql+mysqlconnector://{DB_USER}:{DB_PASS}@{DB_HOST}/{DB_NAME}"
)

st.set_page_config(
    page_title="Task 4 - BI Dashboard & Chat", page_icon="📊", layout="wide"
)

st.title("📊 BI Analytics Dashboard - Stores (Task 4)")
st.markdown(
    "Official dashboard integrating sales data, customers, and chat assistant."
)


@st.cache_data
def load_data():
  try:
    df_orders = pd.read_sql("SELECT * FROM orders", con=engine)
    df_users = pd.read_sql("SELECT * FROM users", con=engine)
    df_books = pd.read_sql("SELECT * FROM books", con=engine)
    return df_orders, df_users, df_books
  except Exception as e:
    st.error(f"Database connection error: {e}")
    return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()


orders_df, users_df, books_df = load_data()

if orders_df.empty:
  st.warning(
      "No data found in database or connection issue. Ensure the ETL script has"
      " been executed."
  )
else:
  orders_df["user_id"] = orders_df["user_id"].astype(str)
  users_df["user_id"] = users_df["user_id"].astype(str)
  if "real_user_id" in users_df.columns:
    users_df["real_user_id"] = users_df["real_user_id"].astype(str)

  orders_df["date"] = pd.to_datetime(orders_df["date"]).dt.strftime(
      "%Y-%m-%d"
  )

  top_days = (
      orders_df.groupby("date")["paid_price"]
      .sum()
      .reset_index()
      .sort_values(by="paid_price", ascending=False)
      .head(5)
  )

  unique_users_count = (
      users_df["real_user_id"].nunique()
      if "real_user_id" in users_df.columns
      else users_df["user_id"].nunique()
  )

  unique_authors_count = books_df["author"].nunique()

  merged_sales = orders_df.merge(
      books_df,
      left_on=["book_id", "store_name"],
      right_on=["id", "store_name"],
      how="inner",
  )
  if not merged_sales.empty:
    top_author = (
        merged_sales.groupby("author")["quantity"]
        .sum()
        .idxmax()
        if "quantity" in merged_sales.columns
        else "No data"
    )
  else:
    top_author = "No data"

  if "real_user_id" in users_df.columns and not orders_df.empty:
    customer_spend = (
        orders_df.merge(users_df, on="user_id", how="inner")
        .groupby("real_user_id")["paid_price"]
        .sum()
    )
    if not customer_spend.empty:
      best_real_user = customer_spend.idxmax()
      best_buyer_aliases = users_df[users_df["real_user_id"] == best_real_user][
          "user_id"
      ].tolist()
    else:
      best_buyer_aliases = []
  else:
    best_buyer_aliases = []

  tab1, tab2, tab3, tab_chat = st.tabs([
      "📈 Overview & Sales",
      "👥 Customers & Best Buyer",
      "📚 Catalog & Authors",
      "💬 Chat Area",
  ])

  with tab1:
    st.subheader("Key Sales Metrics")
    col1, col2, col3 = st.columns(3)
    col1.metric("Total Revenue", f"${orders_df['paid_price'].sum():,.2f}")
    col2.metric("Total Orders", len(orders_df))
    col3.metric("Unique Users", unique_users_count)

    st.markdown("---")
    col_a, col_b = st.columns(2)

    with col_a:
      st.markdown("### 🏆 Top 5 Days by Revenue")
      st.dataframe(
          top_days.rename(
              columns={"date": "Date (YYYY-MM-DD)", "paid_price": "Revenue ($)"}
          ),
          width="stretch",
          hide_index=True,
      )

    with col_b:
      st.markdown("### 📉 Daily Revenue Chart")
      daily_rev = orders_df.groupby("date")["paid_price"].sum().reset_index()
      st.line_chart(daily_rev, x="date", y="paid_price")

  with tab2:
    st.subheader("Customer Analysis & Reconciliation")
    st.info(
        "This section presents aggregated data on unique users and linked"
        " accounts (aliases)."
    )

    col1, col2 = st.columns(2)
    col1.metric("Number of Unique Users", unique_users_count)

    st.markdown("### 👑 Best Buyer (with aliases)")
    st.write(
        "Array containing the primary identifier and associated aliases of the"
        f" best buyer: `{best_buyer_aliases}`"
    )

    st.markdown("### User Reconciliation Sample")
    st.dataframe(
        users_df[["user_id", "name", "real_user_id", "store_name"]].head(10),
        width="stretch",
        hide_index=True,
    )

  with tab3:
    st.subheader("Book Catalog & Authors")
    col1, col2 = st.columns(2)
    col1.metric("Unique Author Sets", unique_authors_count)
    col2.metric("Most Popular Author", top_author)

    st.markdown("### 📖 Top 10 Books in Catalog")
    st.dataframe(
        books_df[["title", "author", "genre", "price", "store_name"]].head(10),
        width="stretch",
        hide_index=True,
    )

  with tab_chat:
    st.subheader("💬 AI Assistant / Chat Area")
    st.markdown(
        "Ask questions regarding analytics, orders, or store statistics:"
    )

    if "messages" not in st.session_state:
      st.session_state.messages = [{
          "role": "assistant",
          "content": (
              "Hello! I am your built-in analytical assistant for the task4"
              " database. How can I help you today?"
          ),
      }]

    for message in st.session_state.messages:
      with st.chat_message(message["role"]):
        st.markdown(message["content"])

    if prompt := st.chat_input(
        "Type a query (e.g., What was the best sales day?)..."
    ):
      st.session_state.messages.append({"role": "user", "content": prompt})
      with st.chat_message("user"):
        st.markdown(prompt)

      response = "Here is the answer based on the current database state: "
      if "top" in prompt.lower() or "day" in prompt.lower():
        top_row = top_days.iloc[0]
        response += (
            f" The best sales day was {top_row['date']} with a total revenue of"
            f" ${top_row['paid_price']:,.2f}."
        )
      elif "author" in prompt.lower():
        response += f" The most popular author is currently: {top_author}."
      elif "customer" in prompt.lower() or "user" in prompt.lower():
        response += f" The total number of unique users is {unique_users_count}."
      else:
        response += (
            " I have processed your request. The dashboard reflects real-time"
            " data from the MySQL database (192.168.101.210)."
        )

      st.session_state.messages.append(
          {"role": "assistant", "content": response}
      )
      with st.chat_message("assistant"):
        st.markdown(response)