
Create your Super Admin account
Run this from the backend folder; it asks for a password and doesn't show it:


.\.venv\Scripts\python.exe -m app.cli create-super-admin --email rahulson.developer@gmail.com --name "Your Name"

Then sign in at http://localhost:4200/login. You'll land on Super Admin → Restaurants, where the test restaurants are waiting for approval.

Your dev servers are running in --reload mode, so they already serve the new code. After you've had a look, say "go ahead" for Phase 3: res


powershell -ExecutionPolicy Bypass -File scripts\dev.ps1

owner@urbanbites.example.com
owner@remelle.example.com
Demo-pass-123

