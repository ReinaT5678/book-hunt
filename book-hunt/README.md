# Book Hunt

Book Hunt is a Flask web app for searching books with the Open Library API and saving books to a personal reading tracker. Users can search by keyword, author, or genre, view book details, and organize books into three lists: Want to Read, Currently Reading, and Finished. 

## What You Need

Before running the app, make sure you have:

- Python3 installed
- A terminal or command prompt

## Project Files

Important files in this project:

- `flask_app.py` - the main Flask application
- `schema.sql` - creates the SQLite database tables
- `templates/` - HTML pages
- `static/css/` - CSS stylesheets
- `instance/app.db` - the SQLite database file, created locally
- `.env` - stores your Flask secret key

## Setup Instructions

Open a terminal and move into the project folder.

Install the required packages:

```bash
pip install Flask requests python-dotenv Werkzeug
```

Create a `.env` file in the project folder with a secret key:

```bash
echo "FLASK_SECRET_KEY=change-this-to-any-random-text" > .env
```

Create the database folder if it does not already exist:

```bash
mkdir -p instance
```

Create the SQLite database from the schema:

```bash
sqlite3 instance/app.db < schema.sql
```

## Run the App

Start the Flask app:

```bash
python flask_app.py
```

When the app starts, open this address in your browser:

```text
http://127.0.0.1:5000
```

## How to Use the App

1. Go to the login page.
2. Enter an email and password. If the email does not exist yet, the app creates a new account.
3. Use the Search page to find books from Open Library.
4. Click a book to open its detail page.
5. Add the book to Want to Read, Currently Reading, or Finished.
6. Go to the Track page to see your reading lists.
7. Drag books between columns to update their status.
8. Use the trash button to remove a book from your tracker.

## Features

- Search books using the Open Library API
- View book covers, authors, publish years, descriptions, and subjects
- Create a user account with an email and password
- Save books to a personal reading list
- Track books in three categories:
  - Want to Read
  - Currently Reading
  - Finished
- Move books between lists with drag and drop
- Delete books from your tracker
- Update your account password from the profile page
- AI powered book recommendation chat using Azure OpenAI.
- NLP-based similar-book recommendations using TF-IDF vectoriation and cosine similarity.
- Cloud deployment on Azure App Service with production startup through Gunicorn.

## Troubleshooting

If Flask says a package is missing, make sure your virtual environment is active and install the packages again:

```bash
source .venv/bin/activate
pip install Flask requests python-dotenv Werkzeug
```

If the app cannot find the database, recreate it:

```bash
mkdir -p instance
sqlite3 instance/app.db < schema.sql
```

## AI and NLP Recommendation 
Book Hunt includes two recommendation workflows. 

The first uses Azure OpenAI to support a natural-language recommendation chat. Users enters a request, then the app sends the prompt to Azure OpenAI to extract structured search terms and genres. Those terms are then used to query the Open Library API and return any book matches. 

The second workflow is a NLP-based similar books recommender built with scikit-learn. For each selected book, the app combines the title, author, description, and subjects into a text document. It then uses the TF-IDF vectorization to convert the text into numerical features and cosine similarity to compare the selected book against candidates. The highest scoring books are displayed.  

## Notes

The app uses SQLite for users, saved books, and reading lists. It does not require MongoDB because MongoDB was optional for this project.
