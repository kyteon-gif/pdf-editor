"""
run.py — 開發用進入點
"""
from pdf_editor import create_app

app = create_app()

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5001)
