@echo off
rem Ders Asistani - tek tikla baslatici (Windows)
rem Ilk calistirmada sanal ortami kurar ve paketleri yukler (internet gerekir, birkac dakika surer).
rem Sonraki calistirmalarda dogrudan uygulamayi acar.
setlocal
chcp 65001 >nul
cd /d "%~dp0"

set "PY=python"
where python >nul 2>nul || set "PY=py -3"
%PY% --version >nul 2>nul
if errorlevel 1 (
  echo [HATA] Python bulunamadi. https://www.python.org adresinden Python 3.11 ya da 3.12 kurun
  echo        ve kurulumda "Add python.exe to PATH" kutusunu isaretleyin.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo [1/3] Sanal ortam olusturuluyor...
  %PY% -m venv .venv
  if errorlevel 1 goto :hata
)

rem requirements.txt degistiyse ya da ilk kurulumsa paketleri yukle
set "ISARET=.venv\kurulum_tamam.txt"
set "KUR=0"
if not exist "%ISARET%" set "KUR=1"
if exist "%ISARET%" (
  fc /b requirements.txt "%ISARET%" >nul 2>nul
  if errorlevel 1 set "KUR=1"
)
if "%KUR%"=="1" (
  echo [2/3] Paketler yukleniyor ^(ilk seferde birkac dakika surebilir^)...
  ".venv\Scripts\python.exe" -m pip install --upgrade pip >nul
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
  if errorlevel 1 goto :hata
  copy /y requirements.txt "%ISARET%" >nul
)

if not exist ".env" (
  copy /y ".env.example" ".env" >nul
  echo [BILGI] .env dosyasi olusturuldu. Gercek ders notlari icin icine GEMINI_API_KEY yazin.
  echo         Anahtar yoksa uygulama demo / cevrimdisi modda calisir.
)

echo [3/3] Uygulama aciliyor: http://localhost:8501
echo        Kapatmak icin bu pencerede Ctrl+C ya da pencereyi kapatin.
".venv\Scripts\python.exe" -m streamlit run app.py
goto :eof

:hata
echo.
echo [HATA] Kurulum tamamlanamadi. Yukaridaki mesaji kontrol edin.
echo        Internet baglantisi ve Python surumu ^(3.11 / 3.12 onerilir^) en sik nedenlerdir.
pause
exit /b 1
