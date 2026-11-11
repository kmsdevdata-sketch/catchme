# Auth & authorization (F12)

Goal: test authenticated APIs **without manual setup**, as close to production as possible,
and state in the report which method was used. Never use production accounts or secrets.

## Order of preference

### 1. `login` — seeded test accounts + the real login API (preferred)
Auth cost (password hashing, session/token issuance) is part of the measurement.

1. Find the password hashing scheme in the code (bcrypt, argon2, scrypt, PBKDF2, Django's
   `pbkdf2_sha256$...`, Spring `DelegatingPasswordEncoder` `{bcrypt}$2a$...`).
2. Compute **one** hash for a test password (e.g. `catchme-test`) with the app's own algorithm,
   inside the app container so the library matches:
   - Node bcrypt: `catchme exec app node -e "console.log(require('bcrypt').hashSync('catchme-test', 10))"`
   - Spring (`BCryptPasswordEncoder`): BCrypt hashes are portable (`$2a$`/`$2b$` both verify), so compute it in a
     throwaway container with the same cost factor (default 10):
     `docker run --rm python:3.12-slim sh -c "pip -q install bcrypt && python -c \"import bcrypt; print(bcrypt.hashpw(b'catchme-test', bcrypt.gensalt(10)).decode())\""`.
     Prefix `{bcrypt}` when the app uses `DelegatingPasswordEncoder` (`PasswordEncoderFactories`). Argon2/scrypt/PBKDF2
     encoders are not portable this way — run a small main class from the app jar instead.
   - Django: `catchme exec app python manage.py shell -c "from django.contrib.auth.hashers import make_password; print(make_password('catchme-test'))"`
3. In `seed.yaml`, override the user table: `email: "'user' || i || '@catchme.test'"`,
   `password: "'<hash>'"`, plus role columns (`role: "CASE WHEN i <= 5 THEN 'ADMIN' ELSE 'USER' END"`).
   Single-quote the hash inside the SQL expression; `$` is fine.
4. In `plan.yaml`:
   ```yaml
   auth:
     mode: login
     login_path: /auth/login
     body: '{"email": "user{n}@catchme.test", "password": "catchme-test"}'
     token_path: token          # dot path in the JSON response (e.g. data.accessToken)
     users: 50                  # VU i uses user ((i-1) % users) + 1
     header: Authorization
     scheme: Bearer             # "" to send the raw token
   ```
   Form logins: set `content_type: application/x-www-form-urlencoded` and a urlencoded `body`.
   Cookie sessions: `token_from: cookie` + `cookie_name: SESSION` (sent back as a Cookie header).

### 2. `token` — mint JWTs with the test secret
When login depends on an external system or is the thing you are *not* testing.
- The secret must be the **test** secret configured in `project.json → app.env` (e.g. `JWT_SECRET=catchme-test-secret`).
- `catchme mint-tokens --secret-env JWT_SECRET --count 50 --claims '{"sub": "{n}", "role": "USER"}' [--exp-seconds 3600]`
  writes `.prod-parity/runs/tokens.json` (HS256). For RS256 apps, configure a test key pair in
  app.env and use the app's own test utilities instead.
- `plan.yaml`: `auth: { mode: token, users: 50 }`.

### 3. mock IdP — external OAuth (Google, Kakao, ...)
`catchme up --with-oauth` starts `mock-oauth2-server` at `http://mock-oauth2:8080` (issuer per
path, e.g. `http://mock-oauth2:8080/default`). Point the app's issuer/JWKS/token URIs at it via
`app.env`. For load, get tokens from its token endpoint in `auth.js` (client_credentials or
a scripted login), or mint locally if the app only validates JWTs via JWKS.

### 4. `bypass` — last resort
A test-only config that disables the auth filter (Spring test profile with `permitAll()`,
Django `DEFAULT_PERMISSION_CLASSES = AllowAny` in a test settings file). Set
`auth: { mode: bypass }`. The report warns: **auth cost not included**, and per-user data
paths may be wrong.

## Authorization (ownership)
Each VU must use resources its own user owns, otherwise you measure 403/404s.
- Most list endpoints are already scoped by the token ("my orders") — nothing to do.
- For `/orders/{id}`-style paths, add an export in `seed.yaml`:
  ```yaml
  exports:
    orders_by_user: |
      SELECT "userId" AS owner, id FROM "Order" WHERE "userId" <= 50 ORDER BY id
  ```
  (columns: `owner`, `id`; at most 200 ids per owner are kept) and use `path: /orders/{own:orders_by_user}`.
- Role-specific endpoints: give admin users low numbers (e.g. 1–5) and a separate run with
  `auth.users`/`user_offset` covering only that range.

## Never
- Real user credentials, production JWT secrets, production OAuth clients.
- Printing tokens or secrets in chat, logs or reports.
