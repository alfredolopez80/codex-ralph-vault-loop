# Attachment Policy

Attachments are not part of Phase 1. The default decision is deny inbound and outbound file handling until the target app proves the controls below.

## Required Before Enabling

- Explicit product need.
- Maximum file size.
- Allowed file types.
- MIME and magic-byte validation.
- Storage under an app-owned safe directory.
- No symlink escape.
- Archive handling policy; block archives until recursive scanning exists.
- Content scan appropriate for the app's risk.
- Retention and deletion rules.
- Egress rules for outbound files.
- RED scan for text-like outbound files.

## Negative Tests

Before approval, the app needs tests for path traversal, symlink escape, oversized file, unexpected MIME, archive denial, binary outbound denial, and RED-looking text file denial.

## Handler Contract

Handlers should receive an attachment descriptor, not a raw path from Telegram. The descriptor should include app-generated storage id, validated type, size, and policy decision.
