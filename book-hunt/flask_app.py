from flask import Flask, render_template, request, redirect, session, g, jsonify
import requests
import sqlite3
from werkzeug.security import generate_password_hash, check_password_hash
import os
import json
import re
from dotenv import load_dotenv 

load_dotenv()
DATABASE = "instance/app.db"

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY")

def get_db():
    db = g.get("db")
    if db is None:
        db = g.db = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row
    return db

def init_db():
    db = sqlite3.connect(DATABASE)
    with open(os.path.join(os.path.dirname(__file__), 'schema.sql')) as f:
        db.executescript(f.read())
    db.commit()
    db.close()

def ensure_database():
    if not os.path.exists(DATABASE):
        os.makedirs(os.path.dirname(DATABASE), exist_ok=True)
        init_db()

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

def search_open_library(params, limit=5):
    response = requests.get(
        "https://openlibrary.org/search.json",
        params={**params, "limit": limit},
        timeout=8
    )
    response.raise_for_status()
    books = []

    for doc in response.json().get("docs", []):
        work_key = doc.get("key", "")
        book_id = work_key.split("/")[-1] if work_key else None
        if not book_id:
            continue

        cover_id = doc.get("cover_i")
        books.append({
            "id": book_id,
            "title": doc.get("title") or "Unknown title",
            "author": ", ".join(doc.get("author_name", [])) if doc.get("author_name") else "Unknown author",
            "first_publish_year": doc.get("first_publish_year"),
            "cover_url": f"https://covers.openlibrary.org/b/id/{cover_id}-M.jpg" if cover_id else None
        })

    return books

def fallback_recommendation_terms(message):
    words = re.findall(r"[a-zA-Z0-9']+", message.lower())
    genre_map = {
        "magic": "fantasy",
        "wizard": "fantasy",
        "dragon": "fantasy",
        "dark": "fantasy",
        "space": "science fiction",
        "alien": "science fiction",
        "murder": "mystery",
        "detective": "mystery",
        "love": "romance",
        "myth": "mythology",
        "mythology": "mythology",
        "greek": "mythology",
        "scary": "horror",
        "adventure": "adventure",
        "history": "history"
    }
    genres = sorted({genre_map[word] for word in words if word in genre_map})
    useful_words = [word for word in words if len(word) > 3][:6]
    return {
        "reply": "I found books based on the main ideas in your request.",
        "search_terms": [" ".join(useful_words)] if useful_words else [message],
        "genres": genres
    }

def parse_recommendation_request(message):
    required_env = [
        "AZURE_OPENAI_ENDPOINT",
        "AZURE_OPENAI_API_KEY",
        "AZURE_OPENAI_DEPLOYMENT",
        "AZURE_OPENAI_API_VERSION"
    ]
    if not all(os.environ.get(name) for name in required_env):
        return fallback_recommendation_terms(message)

    try:
        from openai import AzureOpenAI

        client = AzureOpenAI(
            api_key=os.environ.get("AZURE_OPENAI_API_KEY"),
            api_version=os.environ.get("AZURE_OPENAI_API_VERSION"),
            azure_endpoint=os.environ.get("AZURE_OPENAI_ENDPOINT")
        )

        response = client.chat.completions.create(
            model=os.environ.get("AZURE_OPENAI_DEPLOYMENT"),
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You help a book search app understand recommendation requests. "
                        "Return only valid JSON with keys: reply, search_terms, genres. "
                        "Use short search terms that work well with Open Library."
                    )
                },
                {"role": "user", "content": message}
            ],
            temperature=0.4,
            max_tokens=220
        )

        content = response.choices[0].message.content
        data = json.loads(content)
        return {
            "reply": data.get("reply") or "Here are some books that match your request.",
            "search_terms": data.get("search_terms") or [message],
            "genres": data.get("genres") or []
        }
    except Exception as error:
        print(f"Azure recommendation parsing failed: {error}")
        return fallback_recommendation_terms(message)

def find_recommendation_books(ai_terms):
    seen = set()
    recommendations = []

    searches = []
    for term in ai_terms.get("search_terms", [])[:3]:
        if term:
            searches.append({"q": term})
    for genre in ai_terms.get("genres", [])[:3]:
        if genre:
            searches.append({"subject": genre})

    for params in searches:
        try:
            for book in search_open_library(params, limit=5):
                if book["id"] in seen:
                    continue
                seen.add(book["id"])
                recommendations.append(book)
                if len(recommendations) >= 6:
                    return recommendations
        except requests.RequestException as error:
            print(f"Open Library recommendation search failed: {error}")

    return recommendations

def save_chat_turn(user_message, bot_reply, books):
    chat_history = session.get("chat_history", [])
    chat_history.append({
        "user": user_message,
        "reply": bot_reply,
        "books": books
    })
    session["chat_history"] = chat_history[-8:]
    session.modified = True

@app.context_processor
def inject_logged_in_user():
    current_user_email = None
    if "user_id" in session:
        db = get_db()
        user_row = db.execute(
            "SELECT email FROM users WHERE id = ?",
            (session["user_id"],)
        ).fetchone()
        if user_row:
            current_user_email = user_row["email"]
    return {"current_user_email": current_user_email}

@app.teardown_appcontext
def close_db(error):
    db = g.pop("db", None)
    if db is not None:
        db.close()

@app.route("/")
def home():
    return redirect("/login")

@app.route("/login", methods=["GET", "POST"])
def login():
    ensure_database()
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
                work_key = doc.get("key", "")
                book_id = work_key.split("/")[-1] if work_key else None

                books.append({
                    "id": book_id,
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

@app.route("/recommend", methods=["POST"])
def recommend():
    message = (request.json or {}).get("message", "").strip()
    if not message:
        return jsonify({
            "success": False,
            "error": "Please type what kind of book you want."
        }), 400

    ai_terms = parse_recommendation_request(message)
    books = find_recommendation_books(ai_terms)
    reply = ai_terms.get("reply", "Here are some books that match your request.")
    save_chat_turn(message, reply, books)

    return jsonify({
        "success": True,
        "reply": reply,
        "books": books
    })

@app.route("/chat-history")
def chat_history():
    return jsonify({
        "history": session.get("chat_history", [])
    })

@app.route("/chat-history/clear", methods=["POST"])
def clear_chat_history():
    session.pop("chat_history", None)
    return jsonify({"success": True})

@app.route("/book/<book_id>")
def book_detail(book_id):
    # Fetch work details 
    url = f"https://openlibrary.org/works/{book_id}.json"
    response = requests.get(url)

    if response.status_code != 200:
        return "Book not found."

    data = response.json()

    # cover image 
    cover_id = None 
    if "covers" in data and len(data["covers"]) > 0:
        cover_id = data["covers"][0]

    cover_url = (
        f"https://covers.openlibrary.org/b/id/{cover_id}-L.jpg"
        if cover_id
        else None
    )

    desc = data.get("description")
    if isinstance(desc, dict):
        desc = desc.get("value")

    # Fetch authors
    authors = data.get("authors", [])
    author_names = []
    for auth in authors:
        if "author" in auth and "key" in auth["author"]:
            author_key = auth["author"]["key"].split("/")[-1]
            auth_url = f"https://openlibrary.org/authors/{author_key}.json"
            auth_resp = requests.get(auth_url)
            if auth_resp.status_code == 200:
                auth_data = auth_resp.json()
                author_names.append(auth_data.get("name", "Unknown"))
    author = ", ".join(author_names) if author_names else "Unknown"

    book = {
        "id": book_id,
        "title": data.get("title"),
        "author": author,
        "description": desc or "No description available.",
        "subjects": data.get("subjects", []),
        "cover_url": cover_url,
        "cover_id": cover_id,
        "first_publish_year": data.get("first_publish_date")
    }

    # Check current status for logged-in user
    current_status = None
    if "user_id" in session:
        db = get_db()
        status_row = db.execute(
            "SELECT status FROM reading_list WHERE user_id = ? AND book_id = ?",
            (session["user_id"], book_id)
        ).fetchone()
        if status_row:
            current_status = status_row["status"]

    return render_template("book-detail.html", book=book, current_status=current_status)

@app.route("/track")
def track():
    if "user_id" not in session:
        return redirect("/login")
    
    db = get_db()

    want_to_read = db.execute(
        "SELECT * FROM reading_list JOIN books ON reading_list.book_id = books.id "
        "WHERE user_id = ? AND status = 'want_to_read'",
        (session["user_id"],)
    ).fetchall() 

    reading = db.execute(
        "SELECT * FROM reading_list JOIN books ON reading_list.book_id = books.id "
        "WHERE user_id = ? AND status = 'reading'",
        (session["user_id"],)
    ).fetchall()

    finished = db.execute(
        "SELECT * FROM reading_list JOIN books ON reading_list.book_id = books.id "
        "WHERE user_id = ? AND status = 'finished'",
        (session["user_id"],)
    ).fetchall()

    return render_template("book-track.html", want_to_read=want_to_read, reading=reading, finished=finished)

@app.route("/track/<book_id>", methods=["POST"])
def update_track(book_id):
    if "user_id" not in session:
        return redirect("/login")

    db = get_db()
    if request.is_json:
        payload = request.json
        status = payload.get("status")
        title = payload.get("title")
        author = payload.get("author")
        cover_id = payload.get("cover_id")
        year = payload.get("year")
    else:
        status = request.form.get("status")
        title = request.form.get("title")
        author = request.form.get("author")
        cover_id = request.form.get("cover_id")
        year = request.form.get("year")

    try:
        cover_id = int(cover_id) if cover_id else None
    except (TypeError, ValueError):
        cover_id = None

    try:
        year = int(year) if year else None
    except (TypeError, ValueError):
        year = None

    existing = db.execute("SELECT * FROM books WHERE id = ?", (book_id,)).fetchone()

    if existing is None:
        db.execute(
            "INSERT OR IGNORE INTO books (id, title, author, cover_id, first_publish_year) VALUES (?, ?, ?, ?, ?)",
            (book_id, title or "Unknown Title", author, cover_id, year)
        )
    else:
        updated_title = title if title and title != "Unknown Title" else existing["title"]
        updated_author = author or existing["author"]
        updated_cover_id = cover_id if cover_id is not None else existing["cover_id"]
        updated_year = year if year is not None else existing["first_publish_year"]
        db.execute(
            "UPDATE books SET title = ?, author = ?, cover_id = ?, first_publish_year = ? WHERE id = ?",
            (updated_title, updated_author, updated_cover_id, updated_year, book_id)
        )
    db.commit()

    # Check if user already has the book in their list 
    existing_entry = db.execute(
        "SELECT * FROM reading_list WHERE user_id = ? AND book_id = ?",
        (session["user_id"], book_id)
    ).fetchone()

    if existing_entry:
        # Update status
        db.execute(
            "UPDATE reading_list SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (status, existing_entry["id"])
        )
    else:
        # Insert new entry
        db.execute(
            "INSERT INTO reading_list (user_id, book_id, status) VALUES (?, ?, ?)",
            (session["user_id"], book_id, status)
        )

    db.commit()

    if request.is_json:
        return {"success": True}
    else:
        return redirect(f"/book/{book_id}")


@app.route("/profile")
def profile():
    if "user_id" not in session:
        return redirect("/login")

    db = get_db()
    user = db.execute(
        "SELECT * FROM users WHERE id = ?",
        (session["user_id"],)
    ).fetchone()

    if user is None:
        return redirect("/login")

    return render_template("profile.html", email=user["email"])

@app.route("/track/delete/<book_id>", methods=["POST"])
def delete_track(book_id):
    if "user_id" not in session:
        return redirect("/login")

    db = get_db()
    db.execute(
        "DELETE FROM reading_list WHERE user_id = ? AND book_id = ?",
        (session["user_id"], book_id)
    )
    db.commit()

    return redirect("/track")

@app.route("/update-password", methods=["POST"])
def update_password():
    if "user_id" not in session:
        return redirect("/login")

    data = request.json 
    current_password = data.get("current")
    new_password = data.get("new")
    confirm_password = data.get("confirm")

    if not new_password:
        return {"success": False, "error": "New password cannot be empty"}
    
    db = get_db()
    user = db.execute( 
        "SELECT * FROM users WHERE id = ?",
        (session["user_id"],)
    ).fetchone()

    # Verify the current password 
    if not check_password_hash(user["password_hash"], current_password):
        return {"success": False, "error": "Current password is incorect"}
    
    #Save hte new password 
    new_hash = generate_password_hash(new_password)
    db.execute(
        "UPDATE users SET password_hash = ? WHERE id = ?",
        (new_hash, session["user_id"])
    )
    db.commit()
    return {"success": True}

@app.route("/logout")
def logout():
    session.pop("user_id", None)
    return redirect("/login")

if __name__ == "__main__":
    # Initialize database if it doesn't exist
    if not os.path.exists(DATABASE):
        os.makedirs(os.path.dirname(DATABASE), exist_ok=True)
        init_db()
    app.run(debug=True)
