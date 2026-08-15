# Security audit

This audit covers the private GitHub publication snapshot created on August 14, 2026.

## Release decision

The repository has no unresolved High or Critical findings. It is safe to publish to the private repository after the previously exposed OpenAI API key is revoked and replaced.

## Fixed before publication

- Authentication now defaults to Supabase and fails closed when Supabase is not configured
- UUID based development authentication only works when `APP_ENV` is explicitly `development` or `test`
- The frontend no longer falls back to a shared demo account when auth configuration is missing
- Semester deletion keeps compensation copies on disk instead of retaining every PDF in process memory
- Calendar download filenames use a conservative slug
- Supabase Storage object paths are URL encoded
- PDF page count, OCR page count, and extracted text length have fixed limits
- Local databases, env files, uploaded PDFs, Playwright traces, build output, and dependency directories are ignored by Git

## Remaining work before public production traffic

Two Medium findings remain. They do not block a private source release, but they should be fixed before opening the service to untrusted users.

- Batch upload can retain up to 200 MB of PDF bytes in one API request. Stream files to storage and add an aggregate request limit
- Concurrent reprocess requests can enqueue the same job more than once. Use an atomic state transition and a worker side lock

## Verification

- Backend tests passed with 71 tests
- Frontend tests passed with 105 tests
- Playwright passed all 4 isolated browser flows
- Ruff, TypeScript, and the production build passed
- `npm audit` found 0 vulnerabilities
- `pip-audit` found 0 vulnerabilities
- The staged source secret pattern scan found 0 matching files
