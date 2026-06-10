# Contributing

Thanks for considering a contribution to `monetic-ai-reversal`.

This project is a fintech demo for reversal eligibility, merchant/network rules, batch case processing, and operator-friendly summaries. Contributions should keep the project understandable, runnable locally, and useful for learning payment-flow automation.

## Good Areas to Improve

- Add more sample reversal cases in `data/`.
- Add unit tests for amount calculation, expiry handling, and rule overrides.
- Add Mastercard/Visa-style response-code examples.
- Improve the Next.js UI for audit history and batch result review.
- Add screenshots, diagrams, or a short demo GIF to the README.
- Add Docker Compose for the backend and UI.
- Improve validation errors for malformed JSON, XML, CSV, ZIP, or RAR uploads.

## Local Setup

```bash
python -m venv venv

# Windows
venv\Scripts\activate

# macOS/Linux
source venv/bin/activate

pip install -r requirements.txt
python playground.py
```

For the UI:

```bash
cd ui/agent-ui
pnpm install
pnpm dev -p 3000
```

## Before Opening a PR

Please check the following:

- The backend still starts with `python playground.py`.
- Existing sample files in `data/` still process correctly.
- Any new rules or sample files are documented.
- UI changes are small, focused, and include a short explanation or screenshot.
- No real card data, secrets, tokens, internal URLs, or production payment data are committed.

## Pull Request Style

A good PR should include:

- What changed.
- Why the change is useful.
- How it was tested.
- Any follow-up work or limitations.

Example:

```markdown
## Summary
Add XML sample for expired partial reversal cases.

## Testing
- Ran `python l4_reversal_orchestrator.py data/reversal_expired.xml`
- Confirmed the result is ineligible with expiry notes
```

## Security Notes

This project is a demo. Do not submit real card numbers, real customer data, private company configs, or production credentials. Use masked cards and synthetic examples only.
