"""
run.py — 開發用進入點
生產環境請改用 gunicorn: gunicorn "app:create_app()" -w 2 -b 0.0.0.0:5000
"""

from app import create_app

app = create_app()

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
