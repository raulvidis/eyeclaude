@echo off
cd /d "%~dp0"
echo Creating cross-agent symlinks...

mklink /D .claude\commands .agents\commands && echo OK .claude/commands
mklink /D .opencode\commands .agents\commands && echo OK .opencode/commands
mklink /D .cursor\commands .agents\commands && echo OK .cursor/commands

echo Done.
