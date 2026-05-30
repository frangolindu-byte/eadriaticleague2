@echo off
chcp 65001 >nul
echo ========================================
echo   Robo eAdriatic League
echo ========================================
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo ERRO: Python nao encontrado no PATH.
    echo Instale o Python ou adicione ao PATH.
    pause
    exit /b 1
)

if not exist "credentials.json" (
    echo ERRO: credentials.json nao encontrado.
    echo Coloque o arquivo de credenciais na pasta do projeto.
    pause
    exit /b 1
)

echo Iniciando sincronizacao...
echo.
python main.py

if errorlevel 1 (
    echo.
    echo ERRO: Execucao falhou. Verifique robo.log para detalhes.
) else (
    echo.
    echo Sincronizacao concluida com sucesso.
)

echo.
pause
