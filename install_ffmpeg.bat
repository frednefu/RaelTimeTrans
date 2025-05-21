@echo off
echo Downloading ffmpeg...
powershell -Command "& {Invoke-WebRequest -Uri 'https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip' -OutFile 'ffmpeg.zip'}"

echo Extracting ffmpeg...
powershell -Command "& {Expand-Archive -Path 'ffmpeg.zip' -DestinationPath '.' -Force}"

echo Moving ffmpeg to system path...
copy /Y "ffmpeg-master-latest-win64-gpl\bin\ffmpeg.exe" "C:\Windows\System32\ffmpeg.exe"

echo Cleaning up...
rmdir /S /Q "ffmpeg-master-latest-win64-gpl"
del ffmpeg.zip

echo ffmpeg installation completed!
pause 