@echo off
title Sign Language Interpreter Server
echo.
echo  ============================================
echo   AI Sign Language Interpreter
echo  ============================================
echo.
echo  Installing libraries...
pip install flask flask-cors requests >nul 2>&1
echo  Libraries ready!
echo.
echo  Starting server on port 8080...
echo  Keep this window OPEN!
echo  Open index.html in Chrome after this.
echo.
python server.py
echo.
echo  Server stopped!
pause
