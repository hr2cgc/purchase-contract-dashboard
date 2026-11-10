@echo off
cd /d "%~dp0"
echo [1/2] 배포용 폴더 만드는 중...
py scripts\make_dist.py || goto :fail
echo [2/2] Cloudflare 에 올리는 중...
call npx wrangler pages deploy || goto :fail
echo.
echo 배포 완료. 1분 안에 직원 화면에 반영됩니다.
pause
exit /b 0
:fail
echo.
echo 오류가 났습니다. 이 화면을 캡처해서 보여 주세요.
pause
exit /b 1
