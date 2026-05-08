@echo off
REM ============================================================
REM  HAAS - Hospital Admission Avoidance System
REM  ONE-CLICK SETUP AND RUN SCRIPT
REM  CN7000 MSc Dissertation - University of East London
REM  Author: Urvi Bhatti | Student ID: 2878059
REM ============================================================
REM  This script will:
REM    1. Check if Python is installed
REM    2. Create a virtual environment (if not exists)
REM    3. Install all dependencies (Flask, fpdf2)
REM    4. Generate the synthetic database (if not exists)
REM    5. Start the Flask web server
REM    6. Automatically open the browser to the dashboard
REM ============================================================

echo.
echo ============================================================
echo   HAAS - Hospital Admission Avoidance System
echo   Automated Setup and Launch Script
echo   CN7000 MSc Dissertation - UEL 2025/2026
echo ============================================================
echo.

REM --- Step 1: Check Python Installation ---
echo [Step 1/5] Checking Python installation...
python --version >nul 2>&1
if errorlevel 1 (
    echo.
    echo ERROR: Python is NOT installed on this computer.
    echo Please install Python 3.10+ from https://www.python.org/downloads/
    echo Make sure to tick "Add Python to PATH" during installation.
    echo.
    pause
    exit /b 1
)
echo   Python found: 
python --version
echo.

REM --- Step 2: Create Virtual Environment ---
echo [Step 2/5] Setting up virtual environment...
if not exist "venv" (
    echo   Creating new virtual environment...
    python -m venv venv
    echo   Virtual environment created.
) else (
    echo   Virtual environment already exists.
)
echo.

REM --- Step 3: Activate and Install Dependencies ---
echo [Step 3/5] Installing dependencies...
call venv\Scripts\activate.bat
pip install -q flask>=2.3.0 fpdf2>=2.7.0
echo   Dependencies installed successfully.
echo.

REM --- Step 4: Generate Database ---
echo [Step 4/5] Checking database...
if not exist "data\hospitals.db" (
    echo   Database not found. Generating synthetic dataset...
    python generate_data.py
    echo   Database generated with 220 hospitals and 150 community services.
) else (
    echo   Database already exists. Skipping generation.
)
echo.

REM --- Step 5: Launch the Application ---
echo [Step 5/5] Starting HAAS Web Server...
echo.
echo ============================================================
echo   The application is starting now!
echo   Your browser will open automatically to:
echo   http://localhost:5000
echo.
echo   LOGIN: Use ANY email and ANY password (6+ characters)
echo   This is a DEMO system - no real authentication.
echo.
echo   To STOP the server, press Ctrl+C in this window.
echo ============================================================
echo.

REM Open browser after a short delay
start "" "http://localhost:5000"

REM Start Flask
python app.py

pause
