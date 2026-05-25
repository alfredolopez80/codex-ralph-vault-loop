on run argv
  if (count of argv) is 0 then
    error "Artifact directory argument is required."
  end if

  set artifactDir to item 1 of argv
  set outputPath to artifactDir & "/human-desktop-recording.mov"

  tell application "QuickTime Player"
    activate
    try
      if (count of documents) is 0 then
        error "No QuickTime recording document is open."
      end if

      try
        stop (front document)
      end try
      delay 1
      save (front document) in POSIX file outputPath
      close (front document) saving no
    on error errMsg number errNum
      error "QuickTime could not stop or save the recording automatically. Grant Screen Recording and Accessibility to Codex, Terminal, QuickTime Player, and the active shell, then manually save any open recording to " & outputPath & ". AppleScript error " & errNum & ": " & errMsg
    end try
  end tell
end run
