@echo off
REM run_me.bat - sets up venv, installs requirements, runs safe dry-run

REM 1. Create venv if not exists
IF NOT EXIST venv (
    python -m venv venv
)

REM 2. Activate venv
call venv\Scripts\activate

REM 3. Upgrade pip
python -m pip install --upgrade pip

REM 4. Install requirements
pip install -r requirements.txt

REM 5. Optional extras for GUI/API/PDF (uncomment if needed)
REM pip install reportlab fastapi uvicorn python-multipart

REM 6. Check credentials.json exists
IF NOT EXIST credentials.json (
    echo WARNING: credentials.json not found. Please add your Gmail credentials.json and re-run.
    pause
    exit /b 1
)

REM 7. Run safe dry-run (extractive) summarizer for 1 unread message
echo Running safe dry-run summarizer (no emails will be sent)...
python summarizer.py --query "is:unread" --mode extractive --auto-reply --dry-run --max-results 1

echo Done. If output looks correct, remove --dry-run or use the GUI/API as desired.
pause
