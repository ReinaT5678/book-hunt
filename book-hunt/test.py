import os

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError


os.environ.setdefault("FLASK_SECRET_KEY", "test-secret-key")
os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://bookhunt:bookhunt_password@localhost:5432/bookhunt_test"
)

import flask_app


TEST_SCHEMA = """
DROP TABLE IF EXISTS reading_list;
DROP TABLE IF EXISTS books;
DROP TABLE IF EXISTS users;

CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE books (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    author TEXT,
    cover_id INTEGER,
    first_publish_year INTEGER
);

CREATE TABLE reading_list (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    book_id TEXT NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    status TEXT NOT NULL CHECK (
        status IN ('want_to_read', 'reading', 'finished')
    ),
    rating INTEGER,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""


@pytest.fixture(autouse=True)
def reset_database():
    try:
        with flask_app.engine.begin() as db:
            for statement in TEST_SCHEMA.strip().split(";"):
                statement = statement.strip()
                if statement:
                    db.execute(text(statement))
    except OperationalError as error:
        pytest.fail(
            "Could not connect to the PostgreSQL test database. "
            "Create it first, or set TEST_DATABASE_URL. "
            f"Original error: {error}"
        )


@pytest.fixture
def client():
    flask_app.app.config.update(TESTING=True)
    return flask_app.app.test_client()


def login(client, email="reader@example.com", password="password123"):
    return client.post(
        "/login",
        data={"email": email, "password": password},
        follow_redirects=False,
    )


def test_login_page_loads(client):
    response = client.get("/login")

    assert response.status_code == 200
    assert b"Book Hunt Login" in response.data


def test_login_creates_new_user(client):
    response = login(client)

    assert response.status_code == 302
    assert response.headers["Location"] == "/search"

    with flask_app.engine.connect() as db:
        user = db.execute(
            text("SELECT email FROM users WHERE email = :email"),
            {"email": "reader@example.com"},
        ).mappings().fetchone()

    assert user["email"] == "reader@example.com"


def test_existing_user_rejects_wrong_password(client):
    login(client)

    response = client.post(
        "/login",
        data={"email": "reader@example.com", "password": "wrong-password"},
    )

    assert response.status_code == 200
    assert b"Invalid email or password" in response.data


def test_track_page_requires_login(client):
    response = client.get("/track")

    assert response.status_code == 302
    assert response.headers["Location"] == "/login"


def test_logged_in_user_can_add_book_to_tracker(client):
    login(client)

    response = client.post(
        "/track/OL123W",
        data={
            "status": "want_to_read",
            "title": "Test Book",
            "author": "Test Author",
            "cover_id": "12345",
            "year": "2024",
        },
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["Location"] == "/book/OL123W"

    with flask_app.engine.connect() as db:
        saved_book = db.execute(
            text("SELECT title, author FROM books WHERE id = :book_id"),
            {"book_id": "OL123W"},
        ).mappings().fetchone()
        reading_list_entry = db.execute(
            text(
                "SELECT status FROM reading_list "
                "WHERE book_id = :book_id AND status = :status"
            ),
            {"book_id": "OL123W", "status": "want_to_read"},
        ).mappings().fetchone()

    assert saved_book["title"] == "Test Book"
    assert saved_book["author"] == "Test Author"
    assert reading_list_entry["status"] == "want_to_read"


def test_recommend_returns_books(client, monkeypatch):
    def fake_parse_recommendation_request(message):
        return {
            "reply": "Here are some fantasy picks.",
            "search_terms": ["magic adventure"],
            "genres": ["fantasy"],
        }

    def fake_find_recommendation_books(ai_terms):
        return [
            {
                "id": "OL456W",
                "title": "Mock Fantasy Book",
                "author": "Mock Author",
                "first_publish_year": 2020,
                "cover_url": None,
            }
        ]

    monkeypatch.setattr(
        flask_app,
        "parse_recommendation_request",
        fake_parse_recommendation_request,
    )
    monkeypatch.setattr(
        flask_app,
        "find_recommendation_books",
        fake_find_recommendation_books,
    )

    response = client.post("/recommend", json={"message": "I want magic books"})
    data = response.get_json()

    assert response.status_code == 200
    assert data["success"] is True
    assert data["reply"] == "Here are some fantasy picks."
    assert data["books"][0]["title"] == "Mock Fantasy Book"
