@echo off
chcp 65001 >nul
echo 엑셀 데이터 에디터 빌드를 시작합니다...
echo 필요 패키지를 확인하고 설치합니다...
pip install pyinstaller openpyxl ttkbootstrap sv-ttk
echo.
pyinstaller --noconfirm --onedir --windowed --name "Excel_Data_Editor" "excel_text_editor.py"
echo.
echo 빌드가 완료되었습니다. 'dist\Excel_Data_Editor' 폴더를 확인하세요.
pause