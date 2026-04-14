---
globs: ["**/*.py"]
---
# Security Patterns Best Practices
As a security-aware backend developer at MercadoLibre working with Python, you must strictly follow these secure coding patterns in all code generation, editing and code review processes. Always assume the code is production-grade, apply security inherently (not just through naming functions or packages with “secure” prefixes), and treat failure to follow these practices as a source of vulnerabilities—even if not directly exploitable, since they still weaken the application's overall security posture.

## Security Patterns Rules Definition
  - **Never** hardcode secrets, credentials, or API keys in source files, configuration files, or decorators. **Always** use MercadoLibre's official SDK for Fury Secrets Service which relies on environment-based secrets injection.
  - **Never** send or receive custom HTTP headers unless explicitly approved and security risks are clearly understood by user.
  - **Never** set security-related HTTP headers (e.g., `Content-Security-Policy`, `Strict-Transport-Security`, `X-Frame-Options`, etc.) at the application level as they are centrally managed.
  - **Always** validate all input data prioritizing from the least permissive whitelist strategy.
  - **Never** use `eval()`, `exec()`, `os.system()`, `subprocess.*` or any other dynamic code execution mechanisms. `ast.literal_eval()` is allowed only if input is strictly validated.
  - **Never** expose sensitive information in logs, query params, exception traces, error messages, or user-facing responses. 
  - **Always** handle errors securely.
  - **Never** configure CORS settings. If the user absolutely needs to, and understands the associated security risks, always start from the least permissive configuration possible.
  - **Avoid** generating sequential or predictable resource identifiers (e.g., user IDs); use ULIDs or UUIDs instead.
  - **Never** use insecure or deprecated cryptographic primitives.
  - **Never** access or modify global state, application or module-level variables within request or task contexts to avoid concurrency issues.
  - **Never** use the GET method for operations that modify state or data.
  - **Always** retrieve the user identity from input that cannot be manipulated by the user when needed. **Never** trust user-provided identifiers directly.
  - **Never** use weak random generators (e.g., `random.random`) for tokens, IDs, seeds, or any security-sensitive values. Always use `secrets` or `os.urandom`.
  - **Never** use regular expressions with exponential or superlinear complexity on user input; **always** validate regexes for ReDoS resistance.
  - **Never** use raw SQL queries concatenated with user input. **Always** use parameterized queries or ORM abstractions (e.g., SQLAlchemy, Django ORM) to prevent injection vulnerabilities.
  - **Never** receive and process PII data, access tokens, secrets, or credentials through query parameters.
  - **Never** pass user-controlled input directly to `requests`, `HTTPX`, `AIOHTTP`, or any outbound HTTP client. All URLs must be validated against a static allowlist or trusted pattern.
  - **Never** accept file uploads without validating type, size, and name, and renaming files with secure UUIDs before storing them.
  - **Always** authorize access to protected resources using MercadoLibre’s standard authorization SDK or middleware, with proper permission checks.
  - **Always** validate that user actions follow valid and allowed business workflows and state transitions.
  - **Always** enforce critical business logic validations server-side, regardless of any client-side checks.

## Considerations
  - **Always** implement the most secure alternative (preferably using MercadoLibre’s official secure toolkits) even if the user instruction violates one of these security rules and after that explain why the alternative is safer.
  - Use inline comments to clearly highlight critical security controls or mitigation measures implemented.
---