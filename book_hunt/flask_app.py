from flask import Flask, render_template, request, redirect, session, g
import requests
import sqlite3
from werkzeug.security import generate_password_hash, check_password_hash
import os
 
DATABASE = "instance/app.db"

app = Flask(__name__)
app.secret_key = "your-secret-key-change-this"

def get_db():
    db = g.get("db")
    if db is None:
        db = g.db = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row
    return db

def init_db():
    db = sqlite3.connect(DATABASE)
    with open(os.path.join(os.path.dirname(__file__), '..', 'schema.sql')) as f:
        db.executescript(f.read())
    db.commit()
    db.close()

DEFAULT_GENRES = [
    "Fiction", "Non-fiction", "Mystery", "Romance",
    "Science Fiction", "Fantasy", "Biography", "History",
    "Poetry", "Drama", "Science", "Philosophy", "Art",
    "Travel", "Children's", "Young Adult"
]

def get_genres():
    print("Fetching genres from Open Library API...")
    try:
        response = requests.get("https://openlibrary.org/subjects.json?limit=50", timeout=5)
        response.raise_for_status()
        data = response.json()
        subjects = [subject["name"] for subject in data.get("subjects", []) if subject.get("name")]
        if subjects:
            return subjects
    except requests.RequestException:
        pass
    return DEFAULT_GENRES

@app.teardown_appcontext
def close_db(error):
    db = g.pop("db", None)
    if db is not None:
        db.close()

@app.route("/")
def home():
    return "Hey there this is Book hunt!!"

@app.route("/login", methods=["GET", "POST"])
def login():
    db = get_db()

    if request.method == "POST":
        email = request.form.get("email").strip().lower()
        password = request.form.get("password")

        # Look up user
        user = db.execute(
            "SELECT * FROM users WHERE email = ?",
            (email,)
        ).fetchone()

        # Create new user if not found
        if user is None:
            password_hash = generate_password_hash(password)

            db.execute(
                "INSERT INTO users (email, password_hash) VALUES (?, ?)",
                (email, password_hash)
            )
            db.commit()

            user = db.execute(
                "SELECT * FROM users WHERE email = ?",
                (email,)
            ).fetchone()

            session["user_id"] = user["id"]
            return redirect("/search")

        # Existing user - check password
        if check_password_hash(user["password_hash"], password):
            session["user_id"] = user["id"]
            return redirect("/search")
        else:
            return render_template("login.html", error="Invalid email or password")

    return render_template("login.html")

@app.route("/search", methods=["GET"])
def search():
    query = request.args.get("query", "").strip()
    author = request.args.get("author", "").strip()
    genre = request.args.get("genre", "").strip()
    page_raw = request.args.get("page", "1")

    try:
        page = max(1, int(page_raw))
    except ValueError:
        page = 1

    books = []
    num_found = 0
    total_pages = 1

    if query or author or genre:
        url = "https://openlibrary.org/search.json"
        params = {"limit": 20, "page": page}

        search_text = query or author or genre
        params["q"] = search_text

        if author:
            params["author"] = author
        if genre:
            params["subject"] = genre

        response = requests.get(url, params=params)
        if response.status_code == 200:
            data = response.json()
            num_found = data.get("numFound", 0)
            total_pages = max(1, (num_found + params["limit"] - 1) // params["limit"])

            for doc in data.get("docs", []):
                cover_id = doc.get("cover_i")
                cover_url = (
                    f"https://covers.openlibrary.org/b/id/{cover_id}-M.jpg"
                    if cover_id
                    else None
                )
                books.append({
                    "title": doc.get("title"),
                    "author": ", ".join(doc.get("author_name", [])) if doc.get("author_name") else None,
                    "first_publish_year": doc.get("first_publish_year"),
                    "cover_url": cover_url
                })

    return render_template(
        "search-books.html",
        books=books,
        query=query,
        author=author,
        genre=genre,
        page=page,
        total_pages=total_pages,
        num_found=num_found,
        genres=get_genres()
    )


@app.route("/track")
def track():
    return "Track your books!"

if __name__ == "__main__":
    # Initialize database if it doesn't exist
    if not os.path.exists(DATABASE):
        os.makedirs(os.path.dirname(DATABASE), exist_ok=True)
        init_db()
    app.run(debug=True)