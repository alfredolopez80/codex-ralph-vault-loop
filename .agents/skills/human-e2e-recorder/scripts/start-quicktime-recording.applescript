on run argv
  if (count of argv) is 0 then
    error "Artifact directory argument is required."
  end if

  set artifactDir to item 1 of argv

  try
    tell application "QuickTime Player" to activate
    delay 1
    tell application "System Events"
      tell process "QuickTime Player"
        click menu item "New Screen Recording" of menu "File" of menu bar 1
      end tell
    end tell
    delay 1
  on error errMsg number errNum
    error "QuickTime could not open screen recording. Grant Screen Recording and Accessibility to Codex, Terminal, QuickTime Player, and the active shell, or manually choose the recording area if macOS displays the Screenshot toolbar. Artifact directory: " & artifactDir & ". AppleScript error " & errNum & ": " & errMsg
  end try
end run
